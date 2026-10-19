"""Portable runtime selection must work without a system Vulkan loader."""
from pathlib import Path
import io
import subprocess
from types import SimpleNamespace

import pytest

from core.transcriber import Transcriber
from core.text_optimizer import TextOptimizer, TextOptimizationError
from utils import runtime


@pytest.fixture
def runtimes(tmp_path, monkeypatch):
    paths = {}
    for kind, variable, filename in (("whispercpp", "WHISPERCPP", "whisper-cli.exe"),
                                     ("textoptimizer", "TEXTOPTIMIZER", "llama-server.exe")):
        for cpu in (False, True):
            directory = tmp_path / (kind + ("-cpu" if cpu else ""))
            directory.mkdir()
            executable = directory / filename
            executable.touch()
            if not cpu:
                (directory / "vulkan-1.dll").touch()
            monkeypatch.setenv(f"WINWHISPERPLUS_{variable}{'_CPU' if cpu else ''}_DIR", str(directory))
            paths[kind, cpu] = executable
    return paths


@pytest.mark.parametrize("kind", ["whispercpp", "textoptimizer"])
def test_missing_local_and_system_loader_never_starts_gpu_process(kind, runtimes, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime, "_system_vulkan_loader", lambda: tmp_path / "absent/vulkan-1.dll")
    (runtimes[kind, False].parent / "vulkan-1.dll").unlink()
    monkeypatch.setattr(runtime.subprocess, "run", lambda *_a, **_k: pytest.fail("Missing DLL must not trigger a Windows dialog"))
    assert runtime.select_runtime(kind, "auto") == (runtimes[kind, True], "cpu")
    with pytest.raises(RuntimeError, match="nicht verfügbar"):
        runtime.select_runtime(kind, "gpu:0")


@pytest.mark.parametrize("kind", ["whispercpp", "textoptimizer"])
def test_local_loader_without_driver_uses_cpu(kind, runtimes, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime, "_system_vulkan_loader", lambda: tmp_path / "absent/vulkan-1.dll")
    monkeypatch.setattr(runtime.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr="No Vulkan devices"))
    assert runtime.select_runtime(kind, "auto") == (runtimes[kind, True], "cpu")


@pytest.mark.parametrize("kind", ["whispercpp", "textoptimizer"])
def test_cpu_selection_never_probes_vulkan(kind, runtimes, monkeypatch):
    monkeypatch.setattr(runtime, "vulkan_devices", lambda *_a, **_k: pytest.fail("CPU must not start a Vulkan process"))
    assert runtime.select_runtime(kind, "cpu") == (runtimes[kind, True], "cpu")


@pytest.mark.parametrize("kind", ["whispercpp", "textoptimizer"])
@pytest.mark.parametrize("failure", [OSError("missing loader"), subprocess.TimeoutExpired("probe", 10), None])
def test_auto_falls_back_when_vulkan_cannot_start(kind, failure, runtimes, monkeypatch):
    def run(*args, **kwargs):
        assert kwargs["cwd"] == runtimes[kind, False].parent
        if failure:
            raise failure
        # Even a partial inventory from a failed process must not enable GPU.
        return SimpleNamespace(returncode=0xC0000135, stdout="Vulkan0: GPU", stderr="ggml_vulkan: 0 = GPU")
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.select_runtime(kind, "auto") == (runtimes[kind, True], "cpu")
    with pytest.raises(RuntimeError, match="nicht verfügbar"):
        runtime.select_runtime(kind, "gpu:0")


@pytest.mark.parametrize("kind", ["whispercpp", "textoptimizer"])
def test_available_gpu_and_invalid_selection(kind, runtimes, monkeypatch):
    monkeypatch.setattr(runtime, "_system_vulkan_loader", lambda: None)
    monkeypatch.setattr(runtime.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
        returncode=0, stdout="Available devices:\n  Vulkan2: AMD GPU (8192 MiB)",
        stderr="ggml_vulkan: 2 = AMD GPU | uma: 1"))
    assert runtime.select_runtime(kind, "auto") == (runtimes[kind, False], "auto")
    assert runtime.select_runtime(kind, "gpu:2") == (runtimes[kind, False], "gpu:2")
    with pytest.raises(RuntimeError, match="gpu:7"):
        runtime.select_runtime(kind, "gpu:7")


def test_native_error_dialogs_are_disabled_for_child_processes(monkeypatch):
    import ctypes
    changed = []
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    kernel = SimpleNamespace(GetErrorMode=lambda: 0x0004, SetErrorMode=changed.append)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    runtime.configure_runtime_error_mode()
    assert changed == [0x8007]


def test_frozen_runtime_ignores_developer_overrides(runtimes, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert runtime.runtime_executable("whispercpp", cpu=True) == tmp_path / "bundle/whispercpp-cpu/whisper-cli.exe"


def test_missing_cpu_runtime_has_actionable_error(runtimes):
    runtimes["whispercpp", True].unlink()
    with pytest.raises(RuntimeError, match="vollständige Programmpaket"):
        runtime.select_runtime("whispercpp", "cpu")


def test_transcriber_switch_stops_server_and_selects_cpu(runtimes, monkeypatch):
    monkeypatch.setattr(runtime, "vulkan_devices", lambda *_a, **_k: [(0, "GPU")])
    transcriber = Transcriber()
    monkeypatch.setattr(transcriber, "_load_model", lambda: Path("model.bin"))
    transcriber.load()
    assert transcriber._executable_path == runtimes["whispercpp", False]
    stopped = []
    monkeypatch.setattr(transcriber, "_stop_server", lambda: stopped.append(True))
    transcriber.set_compute_device("cpu")
    transcriber.load()
    assert stopped == [True]
    assert transcriber._executable_path == runtimes["whispercpp", True]
    command = []
    transcriber._append_compute_device_arguments(command)
    assert command == ["--no-gpu"]


def test_optimizer_auto_fallback_and_device_switch(runtimes, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "vulkan_devices", lambda *_a, **_k: [])
    model = tmp_path / "model.gguf"
    model.touch()
    optimizer = TextOptimizer(model_path=model)
    monkeypatch.setattr(optimizer, "_verify_model_hash", lambda: None)
    commands = []
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda **_k: 0)
    def start(command, **kwargs):
        assert kwargs["cwd"] == runtimes["textoptimizer", True].parent
        commands.append(command)
        return process
    monkeypatch.setattr("core.text_optimizer.subprocess.Popen", start)
    monkeypatch.setattr("core.text_optimizer.urllib.request.urlopen", lambda *_a, **_k: io.BytesIO())
    optimizer._ensure_server()
    assert commands[0][0] == str(runtimes["textoptimizer", True])
    assert commands[0][commands[0].index("--n-gpu-layers") + 1] == "0"
    optimizer.set_compute_device("gpu:0")
    assert optimizer._server_process is None
    with pytest.raises(TextOptimizationError, match="nicht verfügbar"):
        optimizer._ensure_server()
    assert len(commands) == 1


@pytest.mark.parametrize("device", ["cpu", "auto", "gpu:0"])
def test_optimizer_uses_matching_runtime_and_arguments(device, runtimes, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "vulkan_devices", lambda *_a, **_k: [(0, "GPU")])
    model = tmp_path / "model.gguf"
    model.touch()
    optimizer = TextOptimizer(compute_device=device, model_path=model)
    monkeypatch.setattr(optimizer, "_verify_model_hash", lambda: None)
    commands = []
    monkeypatch.setattr("core.text_optimizer.subprocess.Popen", lambda command, **_k: commands.append(command)
                        or SimpleNamespace(poll=lambda: None, terminate=lambda: None, wait=lambda **_k: 0))
    monkeypatch.setattr("core.text_optimizer.urllib.request.urlopen", lambda *_a, **_k: io.BytesIO())
    try:
        optimizer._ensure_server()
        assert commands[0][0] == str(runtimes["textoptimizer", device == "cpu"])
        assert commands[0][commands[0].index("--n-gpu-layers") + 1] == ("0" if device == "cpu" else "999")
        if device.startswith("gpu:"):
            assert commands[0][-2:] == ["--device", "Vulkan0"]
    finally:
        optimizer.close()
