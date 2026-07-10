# Easy Video Converter

A simple native **Windows desktop app** that shrinks videos using modern codecs (AV1 / HEVC) to save disk space — without over-processing them. Frame rate, colors, and audio are left alone whenever possible; only the video encoding is modernized.

Built with **Python + PySide6 (Qt)**, packaged into a standalone `.exe` with **PyInstaller**, and shipped as a Windows **Inno Setup** installer. FFmpeg is bundled inside the app, so there is nothing else to install.

## Download

**[⬇ Download EasyVideoConverter-Setup-1.0.0.exe](EasyVideoConverter-Setup-1.0.0.exe)** (Windows 10/11, 64-bit, ~163 MB)

Run the installer and you're done — FFmpeg and the AI models are bundled in, nothing else to install. No admin rights required. Also available on the [Releases page](https://github.com/studyeasy/Easy-Video-Convertor/releases).

The rest of this page is for people who want to build the app from source — most users just need the download above.

## Features

- **Modern codecs** — AV1 (best compression) and HEVC, with H.264 for maximum compatibility. *Auto* picks the most space-efficient codec your hardware supports.
- **GPU acceleration** — detects NVIDIA (NVENC), Intel (QuickSync), and AMD (AMF) hardware encoders at startup and uses the best available. Falls back to CPU encoding (SVT-AV1 / x265) on machines without a supported GPU. If a GPU encode fails mid-file, that file is automatically retried on the CPU.
- **Batch processing** — drag & drop videos or whole folders, or use *Import folder* to queue every video in a folder (subfolders included).
- **Resolution** — keep the original, or downscale to 4K / 1440p / 1080p / 720p. Videos are never upscaled.
- **No over-processing** — audio already in an efficient format (AAC, Opus, MP3, AC-3…) is copied untouched; only raw/PCM audio is re-encoded. 10-bit depth, HDR color flags, subtitles, and metadata are preserved.
- **AI background blur** — NVIDIA-Broadcast-style person blur for talking-head footage: an AI matting model (Robust Video Matting, ONNX) keeps the person sharp and blurs everything behind them, with Low/Med/High/**Cinema** strength (Cinema adds the strongest blur plus a subtle background darken for a movie-like depth-of-field look). Runs on **any GPU** via ONNX Runtime + DirectML (NVIDIA/Intel/AMD); falls back to CPU with a "slow" warning when no compatible GPU exists.
- **Noise reduction** — optional mic noise removal (FFmpeg `arnndn` + bundled RNNoise speech model) and video grain reduction (`hqdn3d`, which also improves compression).
- **Volume normalization** — optional EBU R128 loudness normalization (`loudnorm`) for consistent volume across outputs.
- **Output handling** — pick any output folder; original filenames are kept, and name conflicts get a ` (1)` suffix instead of overwriting.
- **Fully self-contained** — FFmpeg (ffmpeg + ffprobe) is bundled; no external dependencies, works offline.

## Project layout

All source lives under [`Source Code/`](Source%20Code); the repository root keeps
only this README, the changelog, and the installer download.

```
Source Code/
  run_app.py                     Entry point
  easyvideoconverter/            Application package
    app.py                       Bootstrap + entry points (normal / --screenshot / --autotest)
    main_window.py               PySide6 UI
    backend.py                   FFmpeg discovery, encoder detection, probing, arg building
    converter.py                 Background conversion queue (QThread)
    effects.py                   AI background blur (RVM matting + maskedmerge pipeline)
    styles.py                    Dark-theme QSS
  vendor/ffmpeg/                 Bundled ffmpeg.exe + ffprobe.exe (fetched by setup)
  vendor/models/                 RVM matting model (ONNX) + RNNoise model
  assets/                        Icon
  scripts/                       setup / run / build / build-installer batch files
  installer/EasyVideoConverter.iss   Inno Setup script
  EasyVideoConverter.spec        PyInstaller spec
  requirements.txt
  LICENSE                        MIT
```

## Build from source

All commands are run from the `Source Code` folder:

```bat
cd "Source Code"
scripts\setup.bat            :: create .venv, install deps, download bundled FFmpeg
scripts\run.bat              :: run the app from source
scripts\build.bat            :: build dist\EasyVideoConverter\EasyVideoConverter.exe
scripts\build-installer.bat  :: build dist\EasyVideoConverter-Setup-1.0.0.exe (needs Inno Setup 6)
```

### Headless test mode

```bat
scripts\run.bat --autotest="video1.mp4;video2.avi;C:\out\dir"
scripts\run.bat --effects="{\"blur\":\"medium\",\"denoise_audio\":true}" --autotest="in.mp4;C:\out"
```

Converts the given files with default settings (plus optional effect overrides) and prints a JSON report — used for end-to-end verification.
