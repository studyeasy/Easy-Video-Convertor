"""Application bootstrap and entry points (normal, screenshot, autotest)."""

from __future__ import annotations

import os
import sys
import json

from . import APP_NAME, APP_ID


def _set_app_user_model_id():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def _make_qapp():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from .backend import resource_path
    from .styles import QSS

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("StudyEasy")
    check_icon = resource_path(os.path.join("assets", "check.png")).replace("\\", "/")
    app.setStyleSheet(QSS.replace("@CHECK@", check_icon))
    icon_path = resource_path(os.path.join("assets", "icon.ico"))
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    return app


def run() -> int:
    """Normal interactive launch."""
    _set_app_user_model_id()
    app = _make_qapp()
    from .backend import Backend
    from .main_window import MainWindow, DetectWorker

    backend = Backend()
    window = MainWindow(backend)
    window.show()

    if backend.ready:
        worker = DetectWorker(backend)
        worker.done.connect(window.on_detection_done)
        worker.blur_ready.connect(window.on_blur_ready)
        worker.start()
        window._detect_worker = worker  # keep a reference alive

    return app.exec()


def run_screenshot(dest: str) -> int:
    """Render the window to a PNG (used for automated UI verification).

    Uses the real windowing platform so system fonts resolve correctly.
    """
    from PySide6.QtCore import QTimer
    app = _make_qapp()
    from .backend import Backend
    from .main_window import MainWindow

    backend = Backend()
    backend.detect_encoders()          # synchronous for a deterministic shot
    from .effects import MattingEngine
    engine = MattingEngine()
    if engine.load():
        engine.benchmark()
    backend.matting = engine
    window = MainWindow(backend)
    window.resize(1120, 820)
    window.on_detection_done()
    window.on_blur_ready()
    window.show()

    def _grab():
        window.grab().save(dest)
        print(f"screenshot saved: {dest}")
        app.quit()

    QTimer.singleShot(900, _grab)
    return app.exec()


def run_autotest(inputs: list[str], output_dir: str, overrides: dict | None = None) -> int:
    """Headless end-to-end conversion; prints a JSON report."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    from .backend import Backend
    from .converter import ConversionWorker

    backend = Backend()
    backend.detect_encoders()

    jobs, report_index = [], {}
    for i, path in enumerate(inputs):
        info = backend.probe(path)
        jobs.append({"id": i, "path": path, "info": info})
        report_index[i] = {"name": os.path.basename(path), "in_size": info["size"]}

    settings = {"codec": "auto", "quality": "balanced", "resolution": "keep",
                "use_gpu": True, "max_compat": False, "output_dir": output_dir,
                "blur": "off", "denoise_audio": False, "denoise_video": False,
                "normalize_audio": False}
    if overrides:
        settings.update(overrides)

    if settings["blur"] != "off":
        from .effects import MattingEngine
        engine = MattingEngine()
        engine.load()
        backend.matting = engine
        print(f"matting: available={engine.available} provider={engine.provider} "
              f"error={engine.error!r}")
    worker = ConversionWorker(backend, jobs, settings)

    results = {}
    worker.job_started.connect(lambda i, enc: results.setdefault(i, {}).update(encoder=enc))
    worker.job_done.connect(lambda i, sz, p, note: results.setdefault(i, {}).update(
        status="done", out_size=sz, out_path=p, note=note))
    worker.job_failed.connect(lambda i, err: results.setdefault(i, {}).update(
        status="error", error=err))
    worker.run()  # blocking

    report = []
    for i, meta in report_index.items():
        report.append({**meta, **results.get(i, {"status": "unknown"})})
    print("AUTOTEST_RESULT " + json.dumps(report, indent=2))
    return 0


def main() -> int:
    args = sys.argv[1:]
    overrides = None
    for a in args:
        if a.startswith("--effects="):
            overrides = json.loads(a.split("=", 1)[1])
    for a in args:
        if a.startswith("--screenshot="):
            return run_screenshot(a.split("=", 1)[1])
        if a.startswith("--autotest="):
            parts = a.split("=", 1)[1].split(";")
            out = parts.pop()
            return run_autotest(parts, out, overrides)
    return run()
