# Changelog

All notable changes to Easy Video Converter are documented here.

## 1.1.0 — 2026-07-17

### Added
- **Max compatibility mode** — one switch that produces edit-friendly files:
  H.264 (High profile, level 4.2), MP4, constant frame rate, regular keyframes
  (2 s GOP), standard 8-bit yuv420p color, and 48 kHz AAC audio. Files are a
  bit larger, but editing tools (Camtasia, Premiere, Resolve…) scrub and import
  them without crashing. Fixes crashes caused by AV1/HEVC 10-bit or
  variable-frame-rate output being fed into editors.
- **VP9 codec** (libvpx-vp9) — the open web codec used by YouTube; output goes
  to MKV.
- **ProRes codec** (prores_ks) — editing-grade intermediate codec with MOV
  container and uncompressed PCM audio; very large files, flawless scrubbing.
  Quality presets map to ProRes HQ / Standard / LT profiles.

### Changed
- Codec picker now wraps onto two rows (Auto / AV1 / HEVC / H.264 / VP9 /
  ProRes).

## 1.0.0 — 2026-07-10

Initial release.

### Added
- Native Windows desktop app (PySide6) that batch-converts videos to modern
  codecs (AV1 / HEVC / H.264) to save disk space without over-processing.
- **GPU acceleration** — automatic detection of NVIDIA (NVENC), Intel
  (QuickSync), and AMD (AMF) hardware encoders, with CPU fallback (SVT-AV1 /
  x265). A failed GPU encode is automatically retried on the CPU.
- **Auto codec** mode that picks the most space-efficient encoder the hardware
  supports.
- **Quality** presets (High / Balanced / Smallest) and **downscale-only**
  resolution control (Keep / 4K / 1440p / 1080p / 720p).
- **AI background blur** for talking-head footage using Robust Video Matting
  (ONNX) via ONNX Runtime + DirectML — runs on any GPU, CPU fallback. Levels:
  Low / Medium / High / Cinema (Cinema adds a movie-style depth-of-field look).
- **Noise reduction** — mic noise removal (RNNoise) and video grain reduction
  (hqdn3d).
- **Volume normalization** (EBU R128 loudnorm).
- Batch drag & drop, recursive folder import, per-file and overall progress.
- Keeps original filenames; name conflicts get a " (1)" suffix.
- Bundled FFmpeg — fully self-contained, nothing else to install.
- Inno Setup installer (per-user, no admin required).
