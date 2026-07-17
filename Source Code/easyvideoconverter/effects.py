"""AI background blur via person matting (Robust Video Matting, ONNX).

Pipeline: one ffmpeg process decodes frames to raw RGB, the matting model
produces a per-frame person mask, and a second ffmpeg process composites
sharp person over blurred background (gblur + maskedmerge) while encoding
with the normal encoder settings. Runs on any GPU via DirectML, falls back
to CPU automatically.
"""

from __future__ import annotations

import os
import time
import subprocess

import numpy as np

from .backend import (
    Backend, CREATE_NO_WINDOW, resource_path, output_dims, is_10bit,
)

MODEL_REL = os.path.join("vendor", "models", "rvm_mobilenetv3_fp32.onnx")

# gblur sigma at 1080p; scaled by actual output height
BLUR_SIGMA = {"low": 8, "medium": 16, "high": 26, "cinema": 40}

# consider CPU-only matting "slow" above this per-frame budget at 1080p
SLOW_MS_PER_FRAME = 150


class MattingEngine:
    """Loads the RVM model once; thread-safe for inference reuse."""

    def __init__(self):
        self.session = None
        self.provider = ""
        self.ms_per_frame: float | None = None
        self.error = ""

    @property
    def available(self) -> bool:
        return self.session is not None

    @property
    def on_gpu(self) -> bool:
        return "Dml" in self.provider

    @property
    def slow(self) -> bool:
        if not self.available:
            return True
        if self.ms_per_frame is not None:
            return self.ms_per_frame > SLOW_MS_PER_FRAME
        return not self.on_gpu

    def load(self) -> bool:
        try:
            import onnxruntime as ort
            model = resource_path(MODEL_REL)
            if not os.path.isfile(model):
                self.error = "matting model not found"
                return False
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(
                model, sess_options=opts,
                providers=["DmlExecutionProvider", "CPUExecutionProvider"])
            self.provider = self.session.get_providers()[0]
            self._output_names = [o.name for o in self.session.get_outputs()]
            return True
        except Exception as err:  # noqa: BLE001
            self.error = str(err)[:200]
            self.session = None
            return False

    def _zero_rec(self):
        z = np.zeros((1, 1, 1, 1), np.float32)
        return [z, z, z, z]

    def infer(self, src: np.ndarray, rec: list, downsample: float):
        """src: (1,3,H,W) float32 0..1 -> (alpha (H,W) float32, new rec)."""
        outs = self.session.run(self._output_names, {
            "src": src,
            "r1i": rec[0], "r2i": rec[1], "r3i": rec[2], "r4i": rec[3],
            "downsample_ratio": np.array([downsample], np.float32),
        })
        by_name = dict(zip(self._output_names, outs))
        alpha = by_name["pha"][0, 0]
        new_rec = [by_name["r1o"], by_name["r2o"], by_name["r3o"], by_name["r4o"]]
        return alpha, new_rec

    def benchmark(self):
        """Time a 1080p inference (GPU only — CPU is assumed slow)."""
        if not self.available:
            return
        if not self.on_gpu:
            self.ms_per_frame = None
            return
        try:
            frame = np.zeros((1, 3, 1080, 1920), np.float32)
            rec = self._zero_rec()
            _, rec = self.infer(frame, rec, 0.25)   # warmup
            t0 = time.perf_counter()
            n = 3
            for _ in range(n):
                _, rec = self.infer(frame, rec, 0.25)
            self.ms_per_frame = (time.perf_counter() - t0) / n * 1000
        except Exception as err:  # noqa: BLE001
            self.error = str(err)[:200]
            self.session = None


def _downsample_ratio(w: int, h: int) -> float:
    return max(0.125, min(1.0, 480 / max(w, h)))


class BlurPipeline:
    """Decoder -> matting -> masked-merge encoder for a single file."""

    def __init__(self, backend: Backend, engine: MattingEngine,
                 in_path: str, info: dict, settings: dict, encoder: str,
                 out_path: str):
        self.backend = backend
        self.engine = engine
        self.in_path = in_path
        self.info = info
        self.settings = settings
        self.encoder = encoder
        self.out_path = out_path
        self._dec = None
        self._enc = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        for proc in (self._dec, self._enc):
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass

    # -- command construction ----------------------------------------------
    def _commands(self):
        b = self.backend
        info = self.info
        s = self.settings
        w, h, _ = output_dims(info, s)
        fps = info.get("fps") or 30.0
        out_ext = b.output_ext(self.in_path, s)

        level = s.get("blur", "medium")
        sigma = max(2, round(BLUR_SIGMA[level] * h / 1080))
        denoise = ",hqdn3d" if s.get("denoise_video") else ""
        # Cinema: push the background further back with a gentle darken
        # (colorlevels is RGB-native, so the gbrp mask merge stays intact)
        cinema = (",colorlevels=romax=0.90:gomax=0.90:bomax=0.90"
                  if level == "cinema" else "")

        dec_cmd = [
            b.ffmpeg, "-hide_banner", "-loglevel", "error",
            "-i", self.in_path,
            "-vf", f"fps={fps:.6f},scale={w}:{h}:flags=lanczos",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ]

        graph = (
            f"[0:v]fps={fps:.6f},scale={w}:{h}:flags=lanczos{denoise},"
            f"format=gbrp,split[sharp][tob];"
            f"[tob]gblur=sigma={sigma}{cinema}[blurred];"
            f"[1:v]gblur=sigma=1.5,format=gbrp[m];"
            f"[blurred][sharp][m]maskedmerge,format=yuv420p[vout]"
        )

        enc_cmd = [
            b.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", self.in_path,
            "-thread_queue_size", "512",
            "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}",
            "-framerate", f"{fps:.6f}", "-i", "pipe:0",
            "-filter_complex", graph,
            "-map", "[vout]", "-map", "0:a?",
            "-map_metadata", "0",
        ]
        enc_cmd += b.sub_args(info, out_ext)
        max_compat = bool(s.get("max_compat"))
        quality = "high" if max_compat else s["quality"]
        # blur path renders 8-bit SDR frames (RGB round-trip); HDR flags dropped
        enc_cmd += b._video_args(self.encoder, quality, False, out_ext == ".mp4", max_compat)
        enc_cmd += b.audio_args(info, s)
        if max_compat:
            enc_cmd += ["-g", str(max(1, round(fps * 2)))]
        if out_ext == ".mp4":
            enc_cmd += ["-movflags", "+faststart"]
        enc_cmd.append(self.out_path)

        return dec_cmd, enc_cmd, w, h, fps

    # -- run -----------------------------------------------------------------
    def run(self, progress_cb=None) -> int:
        dec_cmd, enc_cmd, w, h, fps = self._commands()
        total_frames = max(1, round((self.info.get("duration") or 0) * fps))
        frame_bytes = w * h * 3
        downsample = _downsample_ratio(w, h)

        self._dec = subprocess.Popen(
            dec_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW)
        self._enc = subprocess.Popen(
            enc_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)

        rec = self.engine._zero_rec()
        frames = 0
        started = time.perf_counter()
        try:
            while not self._cancelled:
                buf = self._dec.stdout.read(frame_bytes)
                if not buf or len(buf) < frame_bytes:
                    break
                frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                src = (frame.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
                alpha, rec = self.engine.infer(src, rec, downsample)
                if alpha.shape != (h, w):
                    # model may return the downsampled alpha; RVM returns full-res
                    raise RuntimeError(f"unexpected mask shape {alpha.shape}")
                mask = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
                self._enc.stdin.write(mask.tobytes())
                frames += 1
                if progress_cb and frames % 5 == 0:
                    elapsed = time.perf_counter() - started
                    speed = (frames / fps) / elapsed if elapsed > 0 else 0
                    progress_cb(min(0.999, frames / total_frames), f"{speed:.2f}x")
        except (BrokenPipeError, OSError):
            pass  # encoder died — its exit code tells the story
        finally:
            try:
                self._enc.stdin.close()
            except Exception:
                pass
            self._dec.wait()
            self._enc.wait()

        if self._cancelled:
            return -1
        if frames == 0:
            return 1
        return self._enc.returncode if self._enc.returncode is not None else 1
