# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Easy Video Converter (one-dir, windowed)."""

block_cipher = None

datas = [
    ("vendor/ffmpeg", "vendor/ffmpeg"),   # bundled ffmpeg.exe + ffprobe.exe + DLLs
    ("vendor/models", "vendor/models"),   # AI matting model + RNNoise model
    ("assets/icon.ico", "assets"),
    ("assets/icon.png", "assets"),
    ("assets/check.png", "assets"),
]

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EasyVideoConverter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="EasyVideoConverter",
)
