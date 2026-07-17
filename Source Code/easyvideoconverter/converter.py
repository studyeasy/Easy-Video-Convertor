"""Background conversion queue running on a QThread."""

from __future__ import annotations

import os
import re
import subprocess

from PySide6.QtCore import QObject, QThread, Signal

from .backend import Backend, unique_output_path, CREATE_NO_WINDOW

_TIME_RE = re.compile(r"(\d+):(\d+):([\d.]+)")


class ConversionWorker(QObject):
    """Converts a list of files sequentially, emitting progress signals.

    Signals carry the file id (index into the caller's list) so the UI can
    map updates back to the right row.
    """

    job_started = Signal(int, str)          # id, encoder
    job_progress = Signal(int, float, str)  # id, fraction 0..1, speed
    job_done = Signal(int, int, str, str)   # id, out_size, out_path, note
    job_failed = Signal(int, str)           # id, error
    queue_finished = Signal(int, int, int, bool)  # done, failed, saved_bytes, cancelled

    def __init__(self, backend: Backend, jobs: list, settings: dict):
        super().__init__()
        self.backend = backend
        self.jobs = jobs            # list of dicts: {id, path, info}
        self.settings = settings
        self._cancel = False
        self._proc: subprocess.Popen | None = None
        self._pipeline = None       # active BlurPipeline, when blur is on

    def cancel(self):
        self._cancel = True
        if self._pipeline:
            self._pipeline.cancel()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    # -- main entry --------------------------------------------------------
    def run(self):
        done = failed = 0
        saved = 0
        cancelled = False
        os.makedirs(self.settings["output_dir"], exist_ok=True)

        for job in self.jobs:
            if self._cancel:
                cancelled = True
                break
            try:
                out_size, out_path, note = self._convert_one(job)
                saved += max(0, job["info"]["size"] - out_size)
                done += 1
                self.job_done.emit(job["id"], out_size, out_path, note or "")
            except _Cancelled:
                cancelled = True
                break
            except Exception as err:  # noqa: BLE001
                failed += 1
                self.job_failed.emit(job["id"], str(err)[:300])

        self.queue_finished.emit(done, failed, saved, cancelled)

    # -- one file ----------------------------------------------------------
    def _convert_one(self, job):
        b = self.backend
        # Max compatibility always encodes H.264 — the codec every tool handles
        codec = "h264" if self.settings.get("max_compat") else self.settings["codec"]
        encoder = b.pick_encoder(codec, self.settings["use_gpu"])
        if not encoder:
            raise RuntimeError("No suitable encoder available")

        base = os.path.splitext(os.path.basename(job["path"]))[0]
        note = ""

        blur_on = self.settings.get("blur", "off") != "off"

        def attempt(enc):
            out_ext = b.output_ext(job["path"], self.settings)
            out_path = unique_output_path(self.settings["output_dir"], base, out_ext)
            self.job_started.emit(job["id"], enc)
            if blur_on:
                code = self._run_blur(job, enc, out_path)
            else:
                args, _ = b.build_args(job["path"], job["info"], self.settings, enc)
                code = self._run_ffmpeg(args, out_path, job["info"]["duration"], job["id"])
            if code != 0 and os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            return code, out_path

        code, out_path = attempt(encoder)

        if code != 0 and not self._cancel:
            fallback = b.cpu_fallback_for(encoder)
            if fallback and fallback != encoder:
                note = "GPU encode failed — retried on CPU"
                encoder = fallback
                code, out_path = attempt(encoder)

        if self._cancel:
            raise _Cancelled()
        if code != 0:
            raise RuntimeError("FFmpeg failed to encode this file")

        return os.path.getsize(out_path), out_path, note

    # -- AI background-blur pipeline ----------------------------------------
    def _run_blur(self, job, encoder, out_path) -> int:
        from .effects import BlurPipeline
        engine = getattr(self.backend, "matting", None)
        if engine is None or not engine.available:
            raise RuntimeError("Background blur is not available on this system")
        pipeline = BlurPipeline(self.backend, engine, job["path"], job["info"],
                                self.settings, encoder, out_path)
        self._pipeline = pipeline
        try:
            return pipeline.run(
                progress_cb=lambda frac, speed:
                    self.job_progress.emit(job["id"], frac, speed))
        finally:
            self._pipeline = None

    # -- ffmpeg subprocess with progress parsing ---------------------------
    def _run_ffmpeg(self, args, out_path, duration, job_id) -> int:
        full = [self.backend.ffmpeg, *args, "-progress", "pipe:1", "-nostats",
                "-loglevel", "error", out_path]
        self._proc = subprocess.Popen(
            full, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
        )
        speed = ""
        for line in self._proc.stdout:
            if self._cancel:
                break
            line = line.strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            out_time = None
            if key == "out_time_us":
                try:
                    out_time = int(val) / 1_000_000
                except ValueError:
                    out_time = None
            elif key == "out_time":
                m = _TIME_RE.search(val)
                if m:
                    out_time = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
            elif key == "speed":
                speed = val.strip()
            if out_time is not None and duration > 0:
                frac = min(0.999, out_time / duration)
                self.job_progress.emit(job_id, frac, speed)
        self._proc.wait()
        code = self._proc.returncode
        self._proc = None
        return code if code is not None else 1


class _Cancelled(Exception):
    pass


class ConversionController(QObject):
    """Owns the worker thread and re-emits its signals."""

    job_started = Signal(int, str)
    job_progress = Signal(int, float, str)
    job_done = Signal(int, int, str, str)
    job_failed = Signal(int, str)
    finished = Signal(int, int, int, bool)

    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, jobs, settings):
        if self.running:
            return
        self._thread = QThread()
        self._worker = ConversionWorker(self.backend, jobs, settings)
        self._worker.moveToThread(self._thread)

        self._worker.job_started.connect(self.job_started)
        self._worker.job_progress.connect(self.job_progress)
        self._worker.job_done.connect(self.job_done)
        self._worker.job_failed.connect(self.job_failed)
        self._worker.queue_finished.connect(self._on_finished)

        self._thread.started.connect(self._worker.run)
        self._thread.start()

    def cancel(self):
        if self._worker:
            self._worker.cancel()

    def _on_finished(self, done, failed, saved, cancelled):
        self._thread.quit()
        self._thread.wait()
        self._worker = None
        self._thread = None
        self.finished.emit(done, failed, saved, cancelled)
