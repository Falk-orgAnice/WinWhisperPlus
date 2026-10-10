# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
import subprocess
import imageio_ffmpeg
from pathlib import Path


block_cipher = None

datas = [
    ("assets/icon.svg", "assets"),
    ("assets/Microphone.ico", "assets"),
    ("assets/licenses", "licenses"),
    ("VERSION", "."),
    ("assets/model-catalog.json", "assets"),
    ("docs/WinWhisperPlus Benutzerhandbuch.pdf", "docs"),
]

# The Windows imageio-ffmpeg wheel contains a locally executable FFmpeg binary.
ffmpeg_source = Path(imageio_ffmpeg.get_ffmpeg_exe())
ffmpeg_runtime = Path("build/ffmpeg-runtime")
ffmpeg_runtime.mkdir(parents=True, exist_ok=True)
import shutil
shutil.copyfile(ffmpeg_source, ffmpeg_runtime / "ffmpeg.exe")
license_text = subprocess.check_output([str(ffmpeg_source), "-L"], stderr=subprocess.STDOUT)
(ffmpeg_runtime / "LICENSE-FFmpeg.txt").write_bytes(license_text)
(ffmpeg_runtime / "BUILD-FFmpeg.txt").write_bytes(subprocess.check_output([str(ffmpeg_source), "-version"], stderr=subprocess.STDOUT))
datas.append((str(ffmpeg_runtime), "ffmpeg"))

whispercpp_dir = Path(os.environ.get("WINWHISPERPLUS_WHISPERCPP_DIR", "build/whispercpp-runtime"))
if not (whispercpp_dir / "whisper-cli.exe").is_file():
    raise SystemExit(
        "whisper.cpp runtime missing. Run scripts/build-release.ps1, which builds it before PyInstaller."
    )
datas.append((str(whispercpp_dir), "whispercpp"))

textoptimizer_dir = Path(os.environ.get("WINWHISPERPLUS_TEXTOPTIMIZER_DIR", "build/textoptimizer-runtime"))
if not (textoptimizer_dir / "llama-server.exe").is_file():
    raise SystemExit(
        "llama.cpp text optimizer runtime missing. Run scripts/build-release.ps1, which builds it before PyInstaller."
    )
if not (textoptimizer_dir / "models" / "Qwen_Qwen3-4B-Q4_K_M.gguf").is_file():
    raise SystemExit(
        "Qwen3 text optimizer model missing. Run scripts/build-release.ps1 to download the bundled model."
    )
if not (textoptimizer_dir / "models" / "text-model.sha256").is_file():
    raise SystemExit("Qwen3 text optimizer checksum missing. Run scripts/build-release.ps1.")
datas.append((str(textoptimizer_dir), "textoptimizer"))

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
    excludes=["imageio_ffmpeg"],  # explicit ffmpeg/ copy above; avoid a duplicate wheel binary
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
