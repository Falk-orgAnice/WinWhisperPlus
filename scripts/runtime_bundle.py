"""Stage redistributable MSVC DLLs and audit the actual Windows package."""
from __future__ import annotations

import argparse
import filecmp
import os
from pathlib import Path
import re
import shutil
import subprocess

import pefile


def stage_microsoft_runtime(directories):
    """Use the licensed Visual Studio redistributables, never System32 copies."""
    redist = os.environ.get("VCToolsRedistDir")
    if redist:
        roots = [Path(redist)]
    else:
        vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        installation = subprocess.check_output(
            [str(vswhere), "-latest", "-products", "*", "-requires",
             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
            text=True, encoding="utf-8",
        ).strip()
        roots = sorted((Path(installation) / "VC/Redist/MSVC").glob("*"),
                       key=lambda path: tuple(int(n) for n in re.findall(r"\d+", path.name)), reverse=True)
    for root in roots:
        folders = [folder for pattern in ("Microsoft.VC*.CRT", "Microsoft.VC*.OpenMP")
                   for folder in (root / "x64").glob(pattern)]
        files = {file.name.lower(): file for folder in folders for file in folder.glob("*.dll")}
        if {"msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll"} <= files.keys():
            for directory in directories:
                directory = Path(directory)
                if not directory.is_dir():
                    raise RuntimeError(f"Runtime directory missing: {directory}")
                for file in files.values():
                    destination = directory / file.name
                    if not destination.is_file() or not filecmp.cmp(file, destination, shallow=False):
                        shutil.copy2(file, destination)
            return
    raise RuntimeError("Complete x64 MSVC CRT/OpenMP redistributables not found in Visual Studio VC/Redist/MSVC")


def stage_vulkan_loader(source: Path, directories):
    """Only GPU runtimes receive the pinned Khronos loader, beside their EXEs."""
    required = ("vulkan-1.dll", "LICENSE-Vulkan-Loader.txt", "LICENSE-cJSON.txt", "BUILD-Vulkan-Loader.txt")
    for name in required:
        if not (source / name).is_file():
            raise RuntimeError(f"Missing Vulkan loader artifact: {source / name}. Run build-release.ps1 -PrepareOnly.")
        for directory in directories:
            destination = Path(directory) / name
            if not destination.is_file() or not filecmp.cmp(source / name, destination, shallow=False):
                shutil.copy2(source / name, destination)


# Windows 10/11 components, rather than third-party DLLs installed on the build host.
_SYSTEM = set("""advapi32 avrt bcrypt bcryptprimitives cfgmgr32 clbcatq comctl32
comdlg32 crypt32 cryptbase cryptsp d2d1 d3d11 d3d12 d3d9 dcomp dbghelp dnsapi
dwmapi dwrite dxcore dxgi dxva2 gdi32 hid imm32 iphlpapi kernel32 kernelbase
mf mfplat mfreadwrite mfuuid mpr msimg32 msvcrt ncrypt netapi32 normaliz ntdll
ntmarta ole32 oleacc oleaut32 opengl32 pdh powrprof propsys psapi rpcrt4
secur32 setupapi shell32 shcore shlwapi sspicli user32 userenv usp10 uxtheme
version win32u windowscodecs winhttp wininet winmm winspool wintrust wldap32
ws2_32 wsock32 wtsapi32 wmvcore glu32 olepro32 urlmon cabinet winusb
authz dhcpcsvc dhcpcsvc6 wlanapi mswsock profapi winnsi nsi srvcli netutils
avicap32 ntdsapi imagehlp evr uiautomationcore icuuc
wevtapi winsta cryptui winmmbase msasn1 samlib rasapi32 msdmo strmiids
dsound ksuser mmdevapi resampledmo d3dcompiler_47 msacm32 usp10 ucrtbase""".split())


def audit_package(package: Path):
    """Fail if a package depends on the developer machine's third-party DLLs."""
    package = package.resolve()
    internal = package / "_internal"
    main = package / "WinWhisperPlus.exe"
    ca_bundle = internal / "certifi/cacert.pem"
    if not ca_bundle.is_file() or b"-----BEGIN CERTIFICATE-----" not in ca_bundle.read_bytes():
        raise RuntimeError("Missing bundled Mozilla CA certificates: certifi/cacert.pem")
    with pefile.PE(str(main), fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
        manifests = []
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id == 24:
                for name in entry.directory.entries:
                    for language in name.directory.entries:
                        data = language.data.struct
                        manifests.append(pe.get_data(data.OffsetToData, data.Size))
        if not any(b'level="asInvoker"' in manifest and b'uiAccess="false"' in manifest for manifest in manifests):
            raise RuntimeError("Application must have an asInvoker manifest without UIAccess")
    required = {"whispercpp": ["whisper-cli.exe", "whisper-server.exe"],
                "textoptimizer": ["llama-server.exe"]}
    for kind, executables in required.items():
        for suffix in ("", "-cpu"):
            for executable in executables:
                if not (internal / (kind + suffix) / executable).is_file():
                    raise RuntimeError(f"Missing {kind}{suffix}/{executable}")
        if not (internal / (kind + "-cpu") / "ggml-cpu-x64.dll").is_file():
            raise RuntimeError(f"Missing baseline CPU backend: {kind}-cpu/ggml-cpu-x64.dll")
        if not (internal / kind / "vulkan-1.dll").is_file():
            raise RuntimeError(f"Missing application-local Vulkan loader: {kind}/vulkan-1.dll")
        if (internal / (kind + "-cpu") / "vulkan-1.dll").exists():
            raise RuntimeError(f"Vulkan loader must not be packaged in CPU runtime: {kind}-cpu")
    errors = []
    for path in package.rglob("*"):
        if path.suffix.lower() not in {".exe", ".dll", ".pyd"}:
            continue
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
            if pe.FILE_HEADER.Machine != 0x8664:
                errors.append(f"Not x64: {path.relative_to(package)}")
            entries = [*getattr(pe, "DIRECTORY_ENTRY_IMPORT", []), *getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])]
            isolated_runtime = path.parent.name in {"whispercpp", "whispercpp-cpu", "textoptimizer", "textoptimizer-cpu"}
            search = [path.parent] if isolated_runtime else [path.parent, internal]
            # These directories are registered by the corresponding PyInstaller
            # runtime hooks / wheel bootstrap, not a machine-wide PATH entry.
            if internal / "PyQt6" in path.parents:
                search.append(internal / "PyQt6/Qt6/bin")
            if path.parent.name in {"win32", "pywin32_system32"}:
                search.append(internal / "pywin32_system32")
            if internal / "numpy" in path.parents:
                search.append(internal / "numpy.libs")
            for entry in entries:
                dll = entry.dll.decode().lower()
                if dll == "vulkan-1.dll":
                    if not isolated_runtime or path.parent.name.endswith("-cpu"):
                        errors.append(f"Unexpected Vulkan dependency: {path.relative_to(package)}")
                    elif not (path.parent / dll).is_file():
                        errors.append(f"{path.relative_to(package)} requires missing local {dll}")
                elif dll.startswith(("api-ms-win-", "ext-ms-win-")) or dll.removesuffix(".dll") in _SYSTEM:
                    continue
                elif not any((directory / dll).is_file() for directory in search):
                    errors.append(f"{path.relative_to(package)} requires missing {dll}")
    # Model weights belong in the user's profile, never in a release package.
    if any(path.suffix.lower() in {".gguf", ".part"} or path.name.startswith("ggml-") and path.suffix == ".bin"
           for path in package.rglob("*")):
        errors.append("Model weights or partial downloads found in program package")
    if errors:
        raise RuntimeError("\n".join(errors))
    print("Package audit: x64, asInvoker, complete local DLL dependencies, Vulkan-free CPU runtimes, no model weights: OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    audit_package(parser.parse_args().package)
