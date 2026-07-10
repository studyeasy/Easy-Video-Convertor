"""FFmpeg discovery, hardware-encoder detection, and media probing.

All the space-saving logic lives here: which encoder to use, quality tables,
argument construction, and the "don't over-process" rules (copy efficient
audio, preserve 10-bit / HDR / subtitles, downscale-only).
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

from . import APP_NAME

# Prevent console windows from flashing when we spawn ffmpeg on Windows.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".flv",
    ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".3gp", ".vob", ".mxf", ".f4v", ".ogv",
}

# Audio already space-efficient -> copy untouched (no over-processing)
EFFICIENT_AUDIO = {"aac", "opus", "mp3", "ac3", "eac3", "vorbis"}
TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

HW_ENCODERS = [
    "av1_nvenc", "hevc_nvenc", "h264_nvenc",
    "av1_qsv", "hevc_qsv", "h264_qsv",
    "av1_amf", "hevc_amf", "h264_amf",
]
CPU_ENCODERS = ["libsvtav1", "libx265", "libx264"]

# Per-encoder quality values for High / Balanced / Smallest
QUALITY = {
    "libsvtav1":  {"high": 26, "balanced": 32, "small": 40},
    "av1_nvenc":  {"high": 28, "balanced": 33, "small": 38},
    "av1_qsv":    {"high": 26, "balanced": 32, "small": 38},
    "av1_amf":    {"high": 26, "balanced": 32, "small": 38},
    "libx265":    {"high": 20, "balanced": 24, "small": 28},
    "hevc_nvenc": {"high": 23, "balanced": 27, "small": 31},
    "hevc_qsv":   {"high": 22, "balanced": 25, "small": 29},
    "hevc_amf":   {"high": 22, "balanced": 26, "small": 30},
    "libx264":    {"high": 19, "balanced": 22, "small": 26},
    "h264_nvenc": {"high": 21, "balanced": 24, "small": 28},
    "h264_qsv":   {"high": 21, "balanced": 24, "small": 28},
    "h264_amf":   {"high": 21, "balanced": 24, "small": 28},
}


def resource_path(rel: str) -> str:
    """Resolve a path both in dev and inside a PyInstaller bundle."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / rel)


def app_data_dir() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run(args, timeout=None):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def _find_binary(name: str) -> str | None:
    """Bundled copy first, then PATH."""
    bundled = resource_path(os.path.join("vendor", "ffmpeg", name + ".exe"))
    if os.path.isfile(bundled):
        return bundled
    return shutil.which(name)


def is_10bit(pix_fmt: str) -> bool:
    return any(d in (pix_fmt or "") for d in ("10", "12", "16"))


def unique_output_path(directory: str, base_name: str, ext: str) -> str:
    candidate = os.path.join(directory, base_name + ext)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base_name} ({n}){ext}")
        n += 1
    return candidate


def output_dims(info: dict, settings: dict) -> tuple[int, int, bool]:
    """Final (width, height, scaled?) after the downscale-only resolution rule."""
    w, h = info["width"] or 0, info["height"] or 0
    if settings.get("resolution", "keep") != "keep":
        target = int(settings["resolution"])
        if min(w, h) > target:
            if w >= h:
                nh = target
                nw = round(w * target / h / 2) * 2
            else:
                nw = target
                nh = round(h * target / w / 2) * 2
            return nw, nh, True
    return w - (w % 2), h - (h % 2), False


def filter_path(p: str) -> str:
    """Escape a Windows path for use inside an ffmpeg filter option."""
    return p.replace("\\", "/").replace(":", "\\:")


class Backend:
    """Holds tool paths + detected encoders and builds ffmpeg commands."""

    def __init__(self):
        self.ffmpeg = _find_binary("ffmpeg")
        self.ffprobe = _find_binary("ffprobe")
        self.encoders: dict[str, bool] = {}
        self.gpus: list[str] = []

    # -- availability ------------------------------------------------------
    @property
    def ready(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    # -- GPU / encoder detection ------------------------------------------
    def detect_gpus(self) -> list[str]:
        if os.name != "nt":
            self.gpus = []
            return self.gpus
        try:
            r = _run([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance Win32_VideoController | "
                "Select-Object -ExpandProperty Name) -join '|'",
            ], timeout=20)
            out = (r.stdout or "").strip()
            self.gpus = [g.strip() for g in out.split("|") if g.strip()] if out else []
        except Exception:
            self.gpus = []
        return self.gpus

    def _test_encoder(self, name: str) -> bool:
        try:
            r = _run([
                self.ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
                "-c:v", name, "-f", "null", "-",
            ], timeout=30)
            return r.returncode == 0
        except Exception:
            return False

    def _cache_file(self) -> Path:
        return app_data_dir() / "hw-cache.json"

    def detect_encoders(self, force: bool = False) -> dict[str, bool]:
        if not self.ffmpeg:
            self.encoders = {}
            return self.encoders

        self.detect_gpus()
        try:
            st = os.stat(self.ffmpeg)
            key = f"{self.ffmpeg}|{int(st.st_mtime)}|{','.join(self.gpus)}"
        except OSError:
            key = self.ffmpeg or ""

        if not force:
            try:
                cached = json.loads(self._cache_file().read_text())
                if cached.get("key") == key and "encoders" in cached:
                    self.encoders = cached["encoders"]
                    return self.encoders
            except Exception:
                pass

        result = {}
        for enc in HW_ENCODERS + CPU_ENCODERS:
            result[enc] = self._test_encoder(enc)
        self.encoders = result
        try:
            self._cache_file().write_text(json.dumps({"key": key, "encoders": result}))
        except Exception:
            pass
        return self.encoders

    def gpu_vendor(self) -> str | None:
        e = self.encoders
        if e.get("av1_nvenc") or e.get("hevc_nvenc") or e.get("h264_nvenc"):
            return "NVIDIA"
        if e.get("av1_qsv") or e.get("hevc_qsv") or e.get("h264_qsv"):
            return "Intel"
        if e.get("av1_amf") or e.get("hevc_amf") or e.get("h264_amf"):
            return "AMD"
        return None

    def codec_available(self, codec: str) -> bool:
        e = self.encoders
        table = {
            "av1": ("av1_nvenc", "av1_qsv", "av1_amf", "libsvtav1"),
            "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"),
            "h264": ("h264_nvenc", "h264_qsv", "h264_amf", "libx264"),
        }
        return any(e.get(x) for x in table.get(codec, ()))

    # -- encoder selection -------------------------------------------------
    def pick_encoder(self, codec: str, use_gpu: bool) -> str | None:
        e = self.encoders
        chains = {
            "av1": ["av1_nvenc", "av1_qsv", "av1_amf", "libsvtav1"],
            "hevc": ["hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"],
            "h264": ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"],
        }
        if codec == "auto":
            order = (chains["av1"] + chains["hevc"]) if use_gpu else ["libsvtav1", "libx265"]
        else:
            order = chains[codec] if use_gpu else [chains[codec][3]]
        for enc in order:
            if not use_gpu and not enc.startswith("lib"):
                continue
            if e.get(enc):
                return enc
        return None

    def cpu_fallback_for(self, encoder: str) -> str | None:
        if "av1" in encoder and self.encoders.get("libsvtav1"):
            return "libsvtav1"
        if ("hevc" in encoder or "265" in encoder) and self.encoders.get("libx265"):
            return "libx265"
        if "264" in encoder and self.encoders.get("libx264"):
            return "libx264"
        return None

    # -- probing -----------------------------------------------------------
    def probe(self, path: str) -> dict:
        r = _run([
            self.ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ], timeout=60)
        if r.returncode != 0:
            raise RuntimeError("Could not read file")
        data = json.loads(r.stdout)
        streams = data.get("streams", [])
        v = next((s for s in streams
                  if s.get("codec_type") == "video"
                  and s.get("disposition", {}).get("attached_pic") != 1), None)
        if not v:
            raise RuntimeError("No video stream")
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        subs = [s for s in streams if s.get("codec_type") == "subtitle"]
        fmt = data.get("format", {})

        def _parse_fps(expr):
            try:
                num, _, den = (expr or "").partition("/")
                value = float(num) / float(den or 1)
                return value if 0 < value < 1000 else 0.0
            except (ValueError, ZeroDivisionError):
                return 0.0

        return {
            "duration": float(fmt.get("duration") or v.get("duration") or 0) or 0.0,
            "size": int(fmt.get("size") or 0),
            "vcodec": v.get("codec_name", ""),
            "width": v.get("width", 0),
            "height": v.get("height", 0),
            "fps": _parse_fps(v.get("avg_frame_rate")) or _parse_fps(v.get("r_frame_rate")) or 30.0,
            "pix_fmt": v.get("pix_fmt", ""),
            "color_trc": v.get("color_transfer", ""),
            "color_primaries": v.get("color_primaries", ""),
            "color_space": v.get("color_space", ""),
            "audio": [{
                "codec": s.get("codec_name", ""),
                "channels": s.get("channels", 2),
            } for s in audio],
            "sub_codecs": [s.get("codec_name", "") for s in subs],
        }

    # -- ffmpeg argument construction -------------------------------------
    def _video_args(self, encoder: str, quality: str, ten_bit: bool, for_mp4: bool) -> list[str]:
        q = str(QUALITY[encoder][quality])
        args = ["-c:v", encoder]
        if encoder in ("av1_nvenc", "hevc_nvenc", "h264_nvenc"):
            args += ["-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", q, "-b:v", "0",
                     "-pix_fmt", "p010le" if (ten_bit and encoder != "h264_nvenc") else "yuv420p"]
        elif encoder in ("av1_qsv", "hevc_qsv", "h264_qsv"):
            args += ["-preset", "slower", "-global_quality", q,
                     "-pix_fmt", "p010le" if (ten_bit and encoder != "h264_qsv") else "yuv420p"]
        elif encoder in ("av1_amf", "hevc_amf", "h264_amf"):
            args += ["-quality", "quality", "-rc", "cqp", "-qp_i", q, "-qp_p", q, "-pix_fmt", "yuv420p"]
        elif encoder == "libsvtav1":
            args += ["-crf", q, "-preset", "6", "-pix_fmt", "yuv420p10le" if ten_bit else "yuv420p"]
        elif encoder == "libx265":
            args += ["-crf", q, "-preset", "medium", "-pix_fmt", "yuv420p10le" if ten_bit else "yuv420p"]
        elif encoder == "libx264":
            args += ["-crf", q, "-preset", "slow", "-pix_fmt", "yuv420p"]
        if for_mp4 and (encoder == "libx265" or encoder.startswith("hevc_")):
            args += ["-tag:v", "hvc1"]
        return args

    def output_ext(self, in_path: str) -> str:
        return ".mp4" if os.path.splitext(in_path)[1].lower() in (".mp4", ".mov", ".m4v") else ".mkv"

    def sub_args(self, info: dict, out_ext: str) -> list[str]:
        subs = info["sub_codecs"]
        if subs and out_ext == ".mkv":
            return ["-map", "0:s?", "-c:s", "copy"]
        if subs and out_ext == ".mp4" and all(c in TEXT_SUB_CODECS for c in subs):
            return ["-map", "0:s?", "-c:s", "mov_text"]
        return []

    def audio_args(self, info: dict, settings: dict) -> list[str]:
        a0 = info["audio"][0] if info["audio"] else None
        if a0 is None:
            return []
        af = []
        if settings.get("denoise_audio"):
            model = filter_path(resource_path(os.path.join("vendor", "models", "bd.rnnn")))
            af.append(f"arnndn=m='{model}'")
        if settings.get("normalize_audio"):
            af.append("loudnorm=I=-16:TP=-1.5:LRA=11")
            af.append("aresample=48000")
        if not af and a0["codec"] in EFFICIENT_AUDIO:
            return ["-c:a", "copy"]
        args = []
        if af:
            args += ["-af", ",".join(af)]
        args += ["-c:a", "aac", "-b:a", "256k" if (a0["channels"] or 2) > 2 else "160k"]
        return args

    def color_args(self, info: dict) -> list[str]:
        args = []
        if info["color_primaries"] and info["color_primaries"] != "unknown":
            args += ["-color_primaries", info["color_primaries"]]
        if info["color_trc"] and info["color_trc"] != "unknown":
            args += ["-color_trc", info["color_trc"]]
        if info["color_space"] and info["color_space"] != "unknown":
            args += ["-colorspace", info["color_space"]]
        return args

    def build_args(self, in_path: str, info: dict, settings: dict, encoder: str):
        ten_bit = is_10bit(info["pix_fmt"])
        out_ext = self.output_ext(in_path)

        args = ["-hide_banner", "-y", "-i", in_path, "-map_metadata", "0",
                "-map", "0:v:0", "-map", "0:a?"]
        args += self.sub_args(info, out_ext)
        args += self._video_args(encoder, settings["quality"], ten_bit, out_ext == ".mp4")
        args += self.color_args(info)

        # video filters: downscale-only resolution, optional grain reduction
        vf = []
        _w, _h, scaled = output_dims(info, settings)
        if scaled:
            target = int(settings["resolution"])
            landscape = (info["width"] or 0) >= (info["height"] or 0)
            vf.append(f"scale=-2:{target}:flags=lanczos" if landscape
                      else f"scale={target}:-2:flags=lanczos")
        if settings.get("denoise_video"):
            vf.append("hqdn3d")
        if vf:
            args += ["-vf", ",".join(vf)]

        args += self.audio_args(info, settings)

        if out_ext == ".mp4":
            args += ["-movflags", "+faststart"]
        return args, out_ext
