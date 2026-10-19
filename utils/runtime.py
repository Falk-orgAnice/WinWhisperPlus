"""Resolve self-contained inference runtimes without installing prerequisites."""
from __future__ import annotations

import os
import logging
from pathlib import Path
import re
import subprocess
import sys


_RUNTIMES = {
    "whispercpp": ("WHISPERCPP", "whisper-cli.exe", "whispercpp-runtime"),
    "textoptimizer": ("TEXTOPTIMIZER", "llama-server.exe", "textoptimizer-runtime"),
}
_WHISPER_DEVICE = re.compile(r"^ggml_vulkan:\s*(\d+)\s*=\s*(.*?)(?:\s*\|.*)?$")
_LLAMA_DEVICE = re.compile(r"^\s*Vulkan(\d+):\s*(.*)")
LOGGER = logging.getLogger("winwhisperplus")


def configure_runtime_error_mode() -> None:
    """Let the app report child-process failures instead of Windows modal boxes."""
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.windll.kernel32
        # Children inherit this process error mode. CREATE_NO_WINDOW alone does
        # not prevent the Windows missing-DLL dialog before their main() runs.
        kernel.SetErrorMode(kernel.GetErrorMode() | 0x8003)


def _system_vulkan_loader() -> Path | None:
    if sys.platform != "win32":
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    return Path(buffer.value) / "vulkan-1.dll" if 0 < length < len(buffer) else None


def _vulkan_loader_available(executable: Path) -> bool:
    if sys.platform != "win32":
        return True
    system = _system_vulkan_loader()
    return (executable.parent / "vulkan-1.dll").is_file() or (system is not None and system.is_file())


def runtime_executable(kind: str, *, cpu: bool = False) -> Path:
    variable, filename, source_directory = _RUNTIMES[kind]
    suffix = "_CPU" if cpu else ""
    configured = os.environ.get(f"WINWHISPERPLUS_{variable}{suffix}_DIR")
    if not getattr(sys, "frozen", False) and configured:
        return Path(configured).resolve() / filename
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return root / (kind + ("-cpu" if cpu else "")) / filename
    root = Path(__file__).resolve().parents[1] / "build"
    return root / (source_directory + ("-cpu" if cpu else "")) / filename


def vulkan_devices(executable: Path, *, kind: str = "whispercpp") -> list[tuple[int, str]]:
    """A missing loader, failed process or timeout means Vulkan is unavailable."""
    if not executable.is_file() or not _vulkan_loader_available(executable):
        return []
    try:
        result = subprocess.run(
            [str(executable), "--help" if kind == "whispercpp" else "--list-devices"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=10,
            cwd=executable.parent,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if getattr(result, "returncode", 0) != 0:
        return []
    pattern = _WHISPER_DEVICE if kind == "whispercpp" else _LLAMA_DEVICE
    devices = []
    for line in f"{result.stdout}\n{result.stderr}".splitlines():
        match = pattern.match(line.strip())
        if match:
            devices.append((int(match[1]), match[2].strip()))
    return devices


def select_runtime(kind: str, device: str) -> tuple[Path, str]:
    """Return the executable and effective device; never change user settings."""
    if device not in {"auto", "cpu"} and not (isinstance(device, str) and device.startswith("gpu:") and device[4:].isdigit()):
        raise ValueError(f"Unsupported compute device: {device}")
    if device != "cpu":
        executable = runtime_executable(kind)
        devices = vulkan_devices(executable, kind=kind)
        if device == "auto" and devices:
            LOGGER.info("Runtime %s | requested=%s effective=Vulkan executable=%s", kind, device, executable)
            return executable, "auto"
        if device.startswith("gpu:"):
            if int(device[4:]) in {index for index, _ in devices}:
                LOGGER.info("Runtime %s | requested=%s executable=%s", kind, device, executable)
                return executable, device
            raise RuntimeError(
                f"Die ausgewählte Vulkan-GPU ({device}) ist nicht verfügbar. "
                "Bitte in den Einstellungen Automatisch oder CPU wählen."
            )
    executable = runtime_executable(kind, cpu=True)
    if not executable.is_file():
        raise RuntimeError(f"CPU-Laufzeit fehlt: {executable}. Bitte das vollständige Programmpaket entpacken.")
    LOGGER.info("Runtime %s | requested=%s effective=CPU executable=%s", kind, device, executable)
    return executable, "cpu"
