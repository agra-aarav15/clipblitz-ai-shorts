# -*- mode: python ; coding: utf-8 -*-
"""One bundle, two executables.

    ClipBlitzStudio.exe          native WebView2 window, no console
    ClipBlitzStudio-server.exe   server / MCP / CLI, console

Both are built from entry.py; the executable name selects the mode. web/ and bin/
are copied next to the EXE by the release workflow (the app reads them from its own
folder), so they are not embedded here.
"""

from PyInstaller.utils.hooks import collect_all

wv_datas, wv_binaries, wv_hidden = collect_all("webview")
pn_datas, pn_binaries, pn_hidden = collect_all("pythonnet")

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=wv_binaries + pn_binaries,
    datas=wv_datas + pn_datas,
    hiddenimports=wv_hidden + pn_hidden + [
        "clr", "pythonnet", "pythonnet.runtime",
        "webview.platforms.edgechromium", "webview.platforms.winforms",
        "Microsoft.Web.WebView2.Core", "Microsoft.Web.WebView2.WinForms",
        "System", "System.Windows.Forms",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)

app = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ClipBlitzStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/ClipBlitzStudio.ico",
)

server = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ClipBlitzStudio-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="assets/ClipBlitzStudio.ico",
)

coll = COLLECT(
    app, server, a.binaries, a.datas,
    strip=False,
    upx=False,
    name="ClipBlitzStudio",
)
