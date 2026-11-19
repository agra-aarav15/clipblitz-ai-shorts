# -*- mode: python ; coding: utf-8 -*-
"""Headless ClipBlitz server for the Electron desktop app.

One executable, no pywebview / pythonnet. web/, bin/, assets/ and plugin/ are staged
next to it by the Electron workflow; the server reads them from its own folder and
writes user data to CB_DATA (Electron's userData directory).
"""

import sys

icon = "assets/ClipBlitzStudio.ico" if sys.platform == "win32" else None

# OpenCV's Haar cascades are data files, not Python modules. Without them the
# packaged facecam detector is installed but silently finds no faces, which is
# exactly the "streamer is missing" bug. Ship the XML cascades with the exe.
try:
    from PyInstaller.utils.hooks import collect_data_files
    cv_data = collect_data_files("cv2", includes=["data/*.xml"])
except Exception:
    cv_data = []

a = Analysis(
    ["server_entry.py"],
    pathex=[],
    binaries=[],
    datas=list(cv_data) + [("clipblitz/models/face_detection_yunet_2023mar.onnx", "clipblitz/models")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "torch", "webview", "pythonnet", "clr"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ClipBlitzStudio-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False,
    upx=False,
    name="ClipBlitzStudio-server",
)
