# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


block_cipher = None

datas = [
    ("assets/icon.svg", "assets"),
    ("assets/Microphone.ico", "assets"),
    ("VERSION", "."),
]

whispercpp_dir = Path(os.environ.get("WINWHISPERPLUS_WHISPERCPP_DIR", "build/whispercpp-runtime"))
if not (whispercpp_dir / "whisper-cli.exe").is_file():
    raise SystemExit(
        "whisper.cpp runtime missing. Run scripts/build-release.ps1, which builds it before PyInstaller."
    )
datas.append((str(whispercpp_dir), "whispercpp"))

hiddenimports = [
    "PyQt6.QtSvg",
]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WinWhisperPlus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/Microphone.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WinWhisperPlus",
)
