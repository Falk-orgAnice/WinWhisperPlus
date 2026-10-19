# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
import subprocess
import imageio_ffmpeg
import runpy
import certifi
from importlib.metadata import distribution


block_cipher = None
configuration = os.environ.get("WINWHISPERPLUS_BUILD_CONFIGURATION", "Release")
if configuration not in {"Debug", "Release"}:
    raise SystemExit("Supported build configurations: Debug, Release")
debug_build = configuration == "Debug"
package_name = os.environ.get("WINWHISPERPLUS_PACKAGE_NAME", "WinWhisperPlus")
if package_name not in {"WinWhisperPlus", "Debug", "Release"}:
    raise SystemExit("Unsupported package directory")

datas = [
    ("assets/icon.svg", "assets"),
    ("assets/Microphone.ico", "assets"),
    ("assets/licenses", "licenses"),
    ("VERSION", "."),
    ("assets/model-catalog.json", "assets"),
    ("docs/WinWhisperPlus Benutzerhandbuch.pdf", "docs"),
]

# Include Mozilla CA roots explicitly, also in a frozen portable application.
datas.append((certifi.where(), "certifi"))
for package in ("certifi", "truststore"):
    metadata = distribution(package)
    for file in metadata.files or []:
        if file.name == "LICENSE":
            datas.append((str(metadata.locate_file(file)), str(Path("licenses") / package)))

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

textoptimizer_dir = Path(os.environ.get("WINWHISPERPLUS_TEXTOPTIMIZER_DIR", "build/textoptimizer-runtime"))
if not (textoptimizer_dir / "llama-server.exe").is_file():
    raise SystemExit(
        "llama.cpp text optimizer runtime missing. Run scripts/build-release.ps1, which builds it before PyInstaller."
    )
# Package the llama.cpp runtime only. Models are downloaded into the user's
# model directory on first launch; exclude cached build models from releases.
whispercpu_dir = Path(os.environ.get("WINWHISPERPLUS_WHISPERCPP_CPU_DIR", "build/whispercpp-runtime-cpu"))
textcpu_dir = Path(os.environ.get("WINWHISPERPLUS_TEXTOPTIMIZER_CPU_DIR", "build/textoptimizer-runtime-cpu"))
for directory, filename in ((whispercpu_dir, "whisper-cli.exe"), (textcpu_dir, "llama-server.exe")):
    if not (directory / filename).is_file():
        raise SystemExit(f"CPU runtime missing: {directory}. Run scripts/build-release.ps1 -PrepareOnly first.")

runtime_tools = runpy.run_path(str(Path(SPECPATH) / "scripts/runtime_bundle.py"))
runtime_tools["stage_microsoft_runtime"]([whispercpp_dir, textoptimizer_dir, whispercpu_dir, textcpu_dir])
runtime_tools["stage_vulkan_loader"](Path("build/vulkan-loader-runtime"), [whispercpp_dir, textoptimizer_dir])
for directory, destination in ((whispercpp_dir, "whispercpp"), (textoptimizer_dir, "textoptimizer"),
                               (whispercpu_dir, "whispercpp-cpu"), (textcpu_dir, "textoptimizer-cpu")):
    for runtime_file in directory.rglob("*"):
        relative = runtime_file.relative_to(directory)
        if runtime_file.is_file() and "models" not in relative.parts:
            datas.append((str(runtime_file), str(Path(destination) / relative.parent)))

hiddenimports = [
    "PyQt6.QtSvg",
    # GetProcessTimes creates pywin32 datetime objects through a dynamic import.
    "win32timezone",
    "truststore._windows",
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
# Analysis also discovers inference DLLs as root-level dependencies. Keep the
# CPU/Vulkan copies isolated: same-named DLLs from these builds are not
# interchangeable, and a root-level ggml.dll would reintroduce Vulkan imports.
inference_dlls = {file.name.lower() for directory in (whispercpp_dir, textoptimizer_dir, whispercpu_dir, textcpu_dir)
                  for file in directory.glob("*.dll") if file.name.lower().startswith(("ggml", "whisper", "llama", "mtmd"))}
inference_dlls.add("vulkan-1.dll")
a.binaries = [entry for entry in a.binaries
              if "/" in entry[0].replace("\\", "/") or entry[0].lower() not in inference_dlls]
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WinWhisperPlus",
    debug=debug_build,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=debug_build,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
    icon="assets/Microphone.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=package_name,
)
