"""The main application window (PySide6)."""

from __future__ import annotations

import os
import json

from PySide6.QtCore import Qt, QObject, QThread, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QMainWindow, QLabel, QPushButton, QCheckBox, QLineEdit,
    QFrame, QScrollArea, QFileDialog, QButtonGroup, QProgressBar,
    QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy,
)

from . import APP_NAME, __version__, AUTHOR_NAME, AUTHOR_URL
from .backend import Backend, app_data_dir, resource_path, VIDEO_EXTS
from .converter import ConversionController


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def fmt_size(n: int) -> str:
    if not n:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.0f} {units[i]}" if (v >= 100 or i == 0) else f"{v:.1f} {units[i]}"


def encoder_label(enc: str) -> str:
    if not enc:
        return ""
    codec = "AV1" if "av1" in enc else ("HEVC" if ("hevc" in enc or "265" in enc) else "H.264")
    via = ("NVIDIA GPU" if "nvenc" in enc else "Intel GPU" if "qsv" in enc
           else "AMD GPU" if "amf" in enc else "CPU")
    return f"{codec} · {via}"


def settings_file():
    return app_data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_file().read_text())
    except Exception:
        return {}


def save_settings(s: dict):
    try:
        settings_file().write_text(json.dumps(s, indent=2))
    except Exception:
        pass


def scan_folder(path: str, out: list):
    for root, _dirs, names in os.walk(path):
        for name in names:
            if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                out.append(os.path.join(root, name))


# ---------------------------------------------------------------------------
# background workers
# ---------------------------------------------------------------------------

class DetectWorker(QThread):
    done = Signal()
    blur_ready = Signal()

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend

    def run(self):
        self.backend.detect_encoders()
        self.done.emit()
        # load the AI matting engine after encoder detection (slower, optional)
        from .effects import MattingEngine
        engine = MattingEngine()
        if engine.load():
            engine.benchmark()
        self.backend.matting = engine
        self.blur_ready.emit()


class ProbeSignals(QObject):
    done = Signal(int, dict)
    fail = Signal(int, str)


class ProbeTask(QRunnable):
    def __init__(self, backend: Backend, file_id: int, path: str):
        super().__init__()
        self.backend = backend
        self.file_id = file_id
        self.path = path
        self.signals = ProbeSignals()

    def run(self):
        try:
            info = self.backend.probe(self.path)
            self.signals.done.emit(self.file_id, info)
        except Exception as err:  # noqa: BLE001
            self.signals.fail.emit(self.file_id, str(err))


# ---------------------------------------------------------------------------
# segmented control
# ---------------------------------------------------------------------------

def make_segmented(options, current, on_change):
    """options: list of (value, label). Returns (widget, button_group, buttons)."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    group = QButtonGroup(row)
    group.setExclusive(True)
    buttons = {}
    for value, label in options:
        btn = QPushButton(label)
        btn.setProperty("seg", "true")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        if value == current:
            btn.setChecked(True)
        group.addButton(btn)
        lay.addWidget(btn)
        buttons[value] = btn
        btn.clicked.connect(lambda _=False, v=value: on_change(v))
    return row, group, buttons


# ---------------------------------------------------------------------------
# file card
# ---------------------------------------------------------------------------

class FileCard(QFrame):
    remove_requested = Signal(int)
    show_requested = Signal(str)

    def __init__(self, file_id: int, path: str):
        super().__init__()
        self.file_id = file_id
        self.path = path
        self.out_path = ""
        self.setObjectName("fileCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 11, 14, 11)
        outer.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.name = QLabel(os.path.basename(path))
        self.name.setObjectName("fcName")
        self.name.setToolTip(path)
        self.name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.meta = QLabel("")
        self.meta.setObjectName("fcMeta")
        self.status = QLabel("Reading…")
        self.status.setObjectName("fcStatus")
        self.show_btn = QPushButton("Show in folder")
        self.show_btn.setObjectName("link")
        self.show_btn.setCursor(Qt.PointingHandCursor)
        self.show_btn.hide()
        self.show_btn.clicked.connect(lambda: self.show_requested.emit(self.out_path))
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("fcRemove")
        self.remove_btn.setCursor(Qt.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.file_id))

        row.addWidget(self.name, 1)
        row.addWidget(self.meta)
        row.addWidget(self.status)
        row.addWidget(self.show_btn)
        row.addWidget(self.remove_btn)
        outer.addLayout(row)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.hide()
        outer.addWidget(self.bar)

        self.error = QLabel("")
        self.error.setObjectName("fcError")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)

    def _set_status(self, text, state=""):
        self.status.setText(text)
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def set_probed(self, info):
        self.meta.setText(
            f"{info['width']}×{info['height']} · {info['vcodec'].upper()} · {fmt_size(info['size'])}"
        )
        self._set_status("Ready")

    def set_bad(self):
        self._set_status("Not a valid video", "error")

    def set_converting(self, frac, speed, encoder):
        pct = int(frac * 100)
        extra = []
        if speed:
            extra.append(speed)
        if encoder:
            extra.append(encoder_label(encoder))
        self._set_status(f"{pct}%" + (" · " + " · ".join(extra) if extra else ""), "converting")
        self.bar.show()
        self.bar.setValue(int(frac * 1000))

    def set_done(self, in_size, out_size, out_path):
        self.out_path = out_path
        self.bar.hide()
        saved = in_size - out_size
        pct = round(saved / in_size * 100) if in_size else 0
        if saved >= 0:
            self._set_status(f"{fmt_size(out_size)} · saved {pct}%", "done")
        else:
            self._set_status(f"{fmt_size(out_size)} · {abs(pct)}% larger", "grew")
        self.show_btn.show()

    def set_error(self, msg):
        self.bar.hide()
        self._set_status("Failed", "error")
        if msg:
            self.error.setText(msg)
            self.error.show()


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.controller = ConversionController(backend)
        self.pool = QThreadPool.globalInstance()

        self.files: dict[int, dict] = {}   # id -> {path, info, status, card}
        self._next_id = 1
        self.running = False

        saved = load_settings()
        self.settings = {
            "codec": saved.get("codec", "auto"),
            "quality": saved.get("quality", "balanced"),
            "resolution": saved.get("resolution", "keep"),
            "use_gpu": saved.get("use_gpu", True),
            "blur": saved.get("blur", "off"),
            "denoise_audio": saved.get("denoise_audio", False),
            "denoise_video": saved.get("denoise_video", False),
            "normalize_audio": saved.get("normalize_audio", False),
        }
        self.output_dir = saved.get("output_dir") or os.path.join(
            os.path.expanduser("~"), "Videos", "Converted")

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(940, 620)
        self.resize(1120, 760)
        icon_path = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setAcceptDrops(True)

        self._build_ui()
        self._wire_controller()
        self._refresh_hw_ui()

    # -- UI construction ---------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())
        outer.addWidget(self._build_banner())

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        body_lay.addWidget(self._build_left(), 1)
        body_lay.addWidget(self._build_sidebar())
        outer.addWidget(body, 1)

    def _build_topbar(self):
        bar = QWidget()
        bar.setObjectName("topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(22, 12, 22, 12)

        left = QVBoxLayout()
        left.setSpacing(1)
        title = QLabel(APP_NAME)
        title.setObjectName("title")
        tag = QLabel("Shrink videos with modern codecs — nothing else changed")
        tag.setObjectName("tagline")
        credit = QLabel(
            f'Created by <a href="{AUTHOR_URL}">{AUTHOR_NAME}</a>')
        credit.setObjectName("credit")
        credit.setOpenExternalLinks(True)
        credit.setTextInteractionFlags(Qt.TextBrowserInteraction)
        credit.setCursor(Qt.PointingHandCursor)
        left.addWidget(title)
        left.addWidget(tag)
        left.addWidget(credit)
        lay.addLayout(left)
        lay.addStretch(1)

        self.hw_badge = QLabel("Detecting hardware…")
        self.hw_badge.setObjectName("hwBadge")
        lay.addWidget(self.hw_badge)
        return bar

    def _build_banner(self):
        self.banner = QWidget()
        self.banner.setObjectName("banner")
        lay = QHBoxLayout(self.banner)
        lay.setContentsMargins(22, 10, 22, 10)
        lay.addStretch(1)
        self.banner_text = QLabel("FFmpeg was not found — video conversion is unavailable.")
        self.banner_text.setObjectName("bannerText")
        lay.addWidget(self.banner_text)
        lay.addStretch(1)
        self.banner.hide()
        return self.banner

    def _build_left(self):
        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(14)

        # drop zone
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        dz = QVBoxLayout(self.drop_zone)
        dz.setAlignment(Qt.AlignCenter)
        dz.setSpacing(8)
        self.dz_title = QLabel("Drop videos or folders here")
        self.dz_title.setObjectName("dzTitle")
        self.dz_title.setAlignment(Qt.AlignCenter)
        self.dz_sub = QLabel("or")
        self.dz_sub.setObjectName("dzSub")
        self.dz_sub.setAlignment(Qt.AlignCenter)
        self.dz_buttons = QWidget()
        btn_row = QHBoxLayout(self.dz_buttons)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setAlignment(Qt.AlignCenter)
        add_files = QPushButton("Add videos")
        add_files.setCursor(Qt.PointingHandCursor)
        add_files.clicked.connect(self.pick_files)
        add_folder = QPushButton("Import folder")
        add_folder.setObjectName("ghost")
        add_folder.setCursor(Qt.PointingHandCursor)
        add_folder.clicked.connect(self.pick_folder)
        btn_row.addWidget(add_files)
        btn_row.addWidget(add_folder)
        dz.addWidget(self.dz_title)
        dz.addWidget(self.dz_sub)
        dz.addWidget(self.dz_buttons)
        lay.addWidget(self.drop_zone, 1)

        # list header
        self.list_header = QWidget()
        hl = QHBoxLayout(self.list_header)
        hl.setContentsMargins(0, 0, 0, 0)
        self.list_count = QLabel("0 videos")
        self.list_count.setObjectName("listCount")
        hl.addWidget(self.list_count)
        hl.addStretch(1)
        for text, cb in (("+ Videos", self.pick_files), ("+ Folder", self.pick_folder),
                         ("Clear all", self.clear_files)):
            b = QPushButton(text)
            b.setObjectName("small")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(cb)
            hl.addWidget(b)
            if text == "Clear all":
                self.clear_btn = b
        self.list_header.hide()
        lay.addWidget(self.list_header)

        # scrollable list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_container = QWidget()
        self.list_container.setObjectName("listContainer")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_container)
        self.scroll.hide()
        lay.addWidget(self.scroll, 3)

        return left

    def _build_sidebar(self):
        container = QWidget()
        container.setObjectName("sidebarWrap")
        container.setFixedWidth(310)
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("sidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        side = QWidget()
        side.setObjectName("sidebar")
        lay = QVBoxLayout(side)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.setSpacing(16)

        head = QLabel("SETTINGS")
        head.setProperty("role", "settingsHead")
        lay.addWidget(head)

        # codec
        lay.addWidget(self._setting_label("Codec"))
        self.codec_row, self.codec_group, self.codec_buttons = make_segmented(
            [("auto", "Auto"), ("av1", "AV1"), ("hevc", "HEVC"), ("h264", "H.264")],
            self.settings["codec"], self._on_codec)
        lay.addWidget(self.codec_row)
        self.codec_hint = self._hint("")
        lay.addWidget(self.codec_hint)
        self._update_codec_hint()

        # quality
        lay.addWidget(self._setting_label("Quality"))
        row, self.quality_group, _ = make_segmented(
            [("high", "High"), ("balanced", "Balanced"), ("small", "Smallest")],
            self.settings["quality"], lambda v: self._set("quality", v))
        lay.addWidget(row)

        # resolution
        lay.addWidget(self._setting_label("Resolution"))
        row, self.res_group, _ = make_segmented(
            [("keep", "Keep"), ("2160", "4K"), ("1440", "1440p"),
             ("1080", "1080p"), ("720", "720p")],
            self.settings["resolution"], lambda v: self._set("resolution", v))
        lay.addWidget(row)
        lay.addWidget(self._hint("Videos are only ever downscaled, never upscaled."))

        # gpu
        self.gpu_check = QCheckBox("Use GPU acceleration")
        self.gpu_check.setChecked(self.settings["use_gpu"])
        self.gpu_check.setCursor(Qt.PointingHandCursor)
        self.gpu_check.toggled.connect(lambda on: self._set("use_gpu", on))
        lay.addWidget(self.gpu_check)
        self.gpu_hint = self._hint("")
        lay.addWidget(self.gpu_hint)

        # effects -----------------------------------------------------------
        eff_head = QLabel("EFFECTS")
        eff_head.setProperty("role", "settingsHead")
        lay.addWidget(eff_head)

        lay.addWidget(self._setting_label("Background blur"))
        self.blur_row, self.blur_group, self.blur_buttons = make_segmented(
            [("off", "Off"), ("low", "Low"), ("medium", "Med"),
             ("high", "High"), ("cinema", "Cinema")],
            self.settings["blur"], lambda v: self._set("blur", v))
        lay.addWidget(self.blur_row)
        self.blur_hint = self._hint("Checking AI blur availability…")
        lay.addWidget(self.blur_hint)

        self.denoise_audio_check = QCheckBox("Remove mic noise")
        self.denoise_audio_check.setChecked(self.settings["denoise_audio"])
        self.denoise_audio_check.setCursor(Qt.PointingHandCursor)
        self.denoise_audio_check.toggled.connect(lambda on: self._set("denoise_audio", on))
        lay.addWidget(self.denoise_audio_check)

        self.denoise_video_check = QCheckBox("Reduce video noise (grain)")
        self.denoise_video_check.setChecked(self.settings["denoise_video"])
        self.denoise_video_check.setCursor(Qt.PointingHandCursor)
        self.denoise_video_check.toggled.connect(lambda on: self._set("denoise_video", on))
        lay.addWidget(self.denoise_video_check)

        self.normalize_check = QCheckBox("Normalize volume")
        self.normalize_check.setChecked(self.settings["normalize_audio"])
        self.normalize_check.setCursor(Qt.PointingHandCursor)
        self.normalize_check.toggled.connect(lambda on: self._set("normalize_audio", on))
        lay.addWidget(self.normalize_check)

        # output
        lay.addWidget(self._setting_label("Output folder"))
        out_row = QHBoxLayout()
        self.out_field = QLineEdit(self.output_dir)
        self.out_field.setObjectName("outDir")
        self.out_field.setReadOnly(True)
        self.out_field.setCursorPosition(len(self.output_dir))
        out_btn = QPushButton("Choose…")
        out_btn.setObjectName("small")
        out_btn.setCursor(Qt.PointingHandCursor)
        out_btn.clicked.connect(self.pick_output)
        out_row.addWidget(self.out_field, 1)
        out_row.addWidget(out_btn)
        lay.addLayout(out_row)
        lay.addWidget(self._hint("Original names are kept; conflicts get a “ (1)” suffix."))

        lay.addStretch(1)
        scroll.setWidget(side)
        col.addWidget(scroll, 1)

        # pinned footer: convert / cancel / progress / summary (never scrolls)
        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        foot = QVBoxLayout(footer)
        foot.setContentsMargins(20, 14, 20, 16)
        foot.setSpacing(10)

        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setCursor(Qt.PointingHandCursor)
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self.start_queue)
        foot.addWidget(self.convert_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.controller.cancel)
        self.cancel_btn.hide()
        foot.addWidget(self.cancel_btn)

        self.overall = QWidget()
        ov = QVBoxLayout(self.overall)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(5)
        self.overall_bar = QProgressBar()
        self.overall_bar.setTextVisible(False)
        self.overall_bar.setRange(0, 1000)
        self.overall_text = QLabel("")
        self.overall_text.setObjectName("overallText")
        self.overall_text.setAlignment(Qt.AlignCenter)
        ov.addWidget(self.overall_bar)
        ov.addWidget(self.overall_text)
        self.overall.hide()
        foot.addWidget(self.overall)

        self.summary = QFrame()
        self.summary.setObjectName("summary")
        sm = QVBoxLayout(self.summary)
        sm.setContentsMargins(12, 12, 12, 12)
        sm.setSpacing(4)
        self.summary_big = QLabel("")
        self.summary_big.setObjectName("summaryBig")
        self.summary_big.setAlignment(Qt.AlignCenter)
        self.summary_text = QLabel("")
        self.summary_text.setObjectName("summaryText")
        self.summary_text.setAlignment(Qt.AlignCenter)
        self.summary_open = QPushButton("Open output folder")
        self.summary_open.setObjectName("small")
        self.summary_open.setCursor(Qt.PointingHandCursor)
        self.summary_open.clicked.connect(lambda: self._open_path(self.output_dir))
        self.summary_big.setWordWrap(True)
        self.summary_text.setWordWrap(True)
        sm.addWidget(self.summary_big)
        sm.addWidget(self.summary_text)
        sm.addWidget(self.summary_open, 0, Qt.AlignHCenter)
        self.summary.hide()
        foot.addWidget(self.summary)

        col.addWidget(footer)
        return container

    def _setting_label(self, text):
        lbl = QLabel(text)
        lbl.setProperty("role", "settingLabel")
        return lbl

    def _hint(self, text):
        lbl = QLabel(text)
        lbl.setProperty("role", "hint")
        lbl.setWordWrap(True)
        return lbl

    # -- settings ----------------------------------------------------------
    def _set(self, key, value):
        self.settings[key] = value
        self._persist()

    def _on_codec(self, value):
        self.settings["codec"] = value
        self._update_codec_hint()
        self._persist()

    def _update_codec_hint(self):
        hints = {
            "auto": "Auto picks the most space-efficient codec your hardware supports.",
            "av1": "AV1 — newest codec, best compression. Playback needs a recent device.",
            "hevc": "HEVC (H.265) — great compression, plays almost everywhere.",
            "h264": "H.264 — largest files of the three, maximum compatibility.",
        }
        self.codec_hint.setText(hints[self.settings["codec"]])

    def _persist(self):
        save_settings({**self.settings, "output_dir": self.output_dir})

    # -- hardware UI -------------------------------------------------------
    def _set_badge(self, text, kind=""):
        self.hw_badge.setText(text)
        self.hw_badge.setProperty("kind", kind)
        self.hw_badge.style().unpolish(self.hw_badge)
        self.hw_badge.style().polish(self.hw_badge)

    def _refresh_hw_ui(self):
        if not self.backend.ready:
            self._set_badge("FFmpeg missing", "cpu")
            self.banner.show()
            self.convert_btn.setEnabled(False)
            return
        self.banner.hide()

        if not self.backend.encoders:
            self._set_badge("Detecting hardware…")
            return

        vendor = self.backend.gpu_vendor()
        if vendor:
            self._set_badge(f"⚡ {vendor} GPU acceleration", "gpu")
            names = ", ".join(self.backend.gpus) or vendor
            self.gpu_hint.setText(f"Hardware encoder detected ({names}). Much faster conversion.")
            self.gpu_check.setEnabled(not self.running)
        else:
            self._set_badge("CPU encoding", "cpu")
            self.gpu_hint.setText("No compatible GPU encoder found — using CPU (works everywhere).")
            self.settings["use_gpu"] = False
            self.gpu_check.setChecked(False)
            self.gpu_check.setEnabled(False)

        for value, btn in self.codec_buttons.items():
            if value != "auto":
                btn.setEnabled(self.backend.codec_available(value))

        self._update_convert_enabled()

    def on_detection_done(self):
        self._refresh_hw_ui()

    def on_blur_ready(self):
        engine = getattr(self.backend, "matting", None)
        if engine is None or not engine.available:
            reason = engine.error if engine else "not loaded"
            self.blur_hint.setText(f"AI blur unavailable on this system ({reason}).")
            for value, btn in self.blur_buttons.items():
                btn.setEnabled(value == "off")
            self.blur_buttons["off"].setChecked(True)
            self.settings["blur"] = "off"
            return
        if engine.on_gpu:
            self.blur_hint.setText(
                "AI person blur — GPU accelerated (DirectML). Keeps the person "
                "sharp, blurs the background. Cinema adds the strongest, "
                "movie-style depth blur.")
        else:
            self.blur_hint.setText(
                "AI person blur — no compatible GPU, runs on CPU. "
                "Works, but conversion will be much slower.")

    # -- adding files ------------------------------------------------------
    def add_paths(self, paths):
        candidates = []
        for p in paths:
            if os.path.isdir(p):
                scan_folder(p, candidates)
            elif os.path.splitext(p)[1].lower() in VIDEO_EXTS:
                candidates.append(p)

        existing = {f["path"].lower() for f in self.files.values()}
        fresh = [p for p in candidates if p.lower() not in existing]

        for path in fresh:
            fid = self._next_id
            self._next_id += 1
            card = FileCard(fid, path)
            card.remove_requested.connect(self.remove_file)
            card.show_requested.connect(self._show_in_folder)
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
            self.files[fid] = {"path": path, "info": None, "status": "probing", "card": card}
            task = ProbeTask(self.backend, fid, path)
            task.signals.done.connect(self.on_probe_done)
            task.signals.fail.connect(self.on_probe_fail)
            self.pool.start(task)

        self._refresh_list_visibility()

    @Slot(int, dict)
    def on_probe_done(self, fid, info):
        f = self.files.get(fid)
        if not f:
            return
        f["info"] = info
        f["status"] = "ready"
        f["card"].set_probed(info)
        self._update_convert_enabled()

    @Slot(int, str)
    def on_probe_fail(self, fid, _err):
        f = self.files.get(fid)
        if not f:
            return
        f["status"] = "bad"
        f["card"].set_bad()
        self._update_convert_enabled()

    def remove_file(self, fid):
        if self.running:
            return
        f = self.files.pop(fid, None)
        if f:
            f["card"].setParent(None)
            f["card"].deleteLater()
        self._refresh_list_visibility()

    def clear_files(self):
        if self.running:
            return
        for f in self.files.values():
            f["card"].setParent(None)
            f["card"].deleteLater()
        self.files.clear()
        self._refresh_list_visibility()

    def _refresh_list_visibility(self):
        n = len(self.files)
        self.list_count.setText("1 video" if n == 1 else f"{n} videos")
        has = n > 0
        self.list_header.setVisible(has)
        self.scroll.setVisible(has)
        # collapse the drop zone into a slim hint bar once we have files
        self.dz_sub.setVisible(not has)
        self.dz_buttons.setVisible(not has)
        self.dz_title.setText("Drop more videos or folders here"
                              if has else "Drop videos or folders here")
        self.drop_zone.setMaximumHeight(56 if has else 16777215)
        self.drop_zone.setProperty("compact", "true" if has else "false")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        self._update_convert_enabled()

    def _update_convert_enabled(self):
        ready = any(f["status"] in ("ready", "error") for f in self.files.values())
        ok = (self.backend.ready and bool(self.backend.encoders)
              and ready and not self.running)
        self.convert_btn.setEnabled(ok)

    # -- dialogs -----------------------------------------------------------
    def pick_files(self):
        exts = " ".join("*" + e for e in sorted(VIDEO_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Add videos", "", f"Videos ({exts})")
        if paths:
            self.add_paths(paths)

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Import all videos from a folder")
        if d:
            self.add_paths([d])

    def pick_output(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_dir)
        if d:
            self.output_dir = d
            self.out_field.setText(d)
            self.out_field.setCursorPosition(len(d))
            self._persist()

    # -- conversion --------------------------------------------------------
    def _wire_controller(self):
        self.controller.job_started.connect(self.on_job_started)
        self.controller.job_progress.connect(self.on_job_progress)
        self.controller.job_done.connect(self.on_job_done)
        self.controller.job_failed.connect(self.on_job_failed)
        self.controller.finished.connect(self.on_queue_finished)

    def start_queue(self):
        if self.running:
            return
        jobs = [{"id": fid, "path": f["path"], "info": f["info"]}
                for fid, f in self.files.items()
                if f["status"] in ("ready", "error") and f["info"]]
        if not jobs:
            return
        self.summary.hide()
        self._set_running(True)
        settings = {**self.settings, "output_dir": self.output_dir}
        self._total_jobs = len(jobs)
        self._done_jobs = 0
        self._current = None
        self.controller.start(jobs, settings)

    def _set_running(self, on):
        self.running = on
        self.cancel_btn.setVisible(on)
        self.convert_btn.setVisible(not on)
        self.overall.setVisible(on)
        for w in (self.codec_row, self.quality_group, self.res_group):
            pass
        for btn in list(self.codec_buttons.values()):
            btn.setEnabled(not on and (btn is self.codec_buttons["auto"]
                                       or self.backend.codec_available(
                                           [k for k, v in self.codec_buttons.items() if v is btn][0])))
        for grp in (self.quality_group, self.res_group):
            for b in grp.buttons():
                b.setEnabled(not on)
        engine = getattr(self.backend, "matting", None)
        blur_ok = engine is not None and engine.available
        for value, b in self.blur_buttons.items():
            b.setEnabled(not on and (blur_ok or value == "off"))
        for chk in (self.denoise_audio_check, self.denoise_video_check, self.normalize_check):
            chk.setEnabled(not on)
        self.clear_btn.setEnabled(not on)
        if not self.gpu_check.property("perma"):
            self.gpu_check.setEnabled(not on and self.backend.gpu_vendor() is not None)
        if on:
            self.overall_bar.setValue(0)
            self.overall_text.setText("Starting…")
        else:
            self._refresh_hw_ui()
        self._update_convert_enabled()

    @Slot(int, str)
    def on_job_started(self, fid, encoder):
        f = self.files.get(fid)
        if f:
            f["status"] = "converting"
            f["encoder"] = encoder
            f["card"].set_converting(0, "", encoder)
            self._current = fid
            self.overall_text.setText(f"Converting {os.path.basename(f['path'])}")

    @Slot(int, float, str)
    def on_job_progress(self, fid, frac, speed):
        f = self.files.get(fid)
        if f:
            f["card"].set_converting(frac, speed, f.get("encoder", ""))
            self._update_overall(frac)

    @Slot(int, int, str, str)
    def on_job_done(self, fid, out_size, out_path, note):
        f = self.files.get(fid)
        if f:
            f["status"] = "done"
            f["card"].set_done(f["info"]["size"], out_size, out_path)
        self._done_jobs += 1
        self._update_overall(0)

    @Slot(int, str)
    def on_job_failed(self, fid, err):
        f = self.files.get(fid)
        if f:
            f["status"] = "error"
            f["card"].set_error(err)
        self._done_jobs += 1
        self._update_overall(0)

    def _update_overall(self, current_frac):
        total = getattr(self, "_total_jobs", 0)
        if not total:
            return
        frac = (self._done_jobs + current_frac) / total
        self.overall_bar.setValue(int(frac * 1000))
        self.overall_text.setText(f"{self._done_jobs} of {total} done")

    @Slot(int, int, int, bool)
    def on_queue_finished(self, done, failed, saved, cancelled):
        self._set_running(False)
        if cancelled:
            self.summary_big.setText("Cancelled")
            self.summary_text.setText(f"{done} file(s) finished before stopping.")
            self.summary_open.setVisible(done > 0)
        else:
            self.summary_big.setText(f"Saved {fmt_size(saved)}")
            extra = f", {failed} failed" if failed else ""
            self.summary_text.setText(f"{done} converted{extra}")
            self.summary_open.setVisible(True)
        self.summary.show()

    # -- misc --------------------------------------------------------------
    def _open_path(self, path):
        if path and os.path.isdir(path):
            os.startfile(path)  # noqa: S606 (Windows-only)

    def _show_in_folder(self, path):
        if path and os.path.isfile(path):
            os.system(f'explorer /select,"{os.path.normpath(path)}"')

    # -- drag & drop -------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.setProperty("drag", "true")
            self.drop_zone.style().unpolish(self.drop_zone)
            self.drop_zone.style().polish(self.drop_zone)

    def dragLeaveEvent(self, event):
        self.drop_zone.setProperty("drag", "false")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def dropEvent(self, event):
        self.drop_zone.setProperty("drag", "false")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.add_paths(paths)
