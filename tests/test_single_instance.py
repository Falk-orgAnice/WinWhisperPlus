import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import pytest

from utils.single_instance import SingleInstance, _legacy_instance_running, _process_identity

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows instance gate")
ROOT = Path(__file__).resolve().parents[1]


def test_mutex_rejects_second_handle_and_allows_restart():
    name = "Global\\WinWhisperPlus.Test." + uuid.uuid4().hex
    first = SingleInstance(name, detect_legacy=False)
    second = SingleInstance(name, detect_legacy=False)
    try:
        assert first.acquire()
        assert first.acquire()  # idempotent; no second handle leaked
        assert not second.acquire()
        first.close()
        assert second.acquire()
    finally:
        first.close()
        second.close()


def test_process_exit_releases_mutex_without_cleanup():
    name = "Global\\WinWhisperPlus.Test." + uuid.uuid4().hex
    code = "from utils.single_instance import SingleInstance; import sys; s=SingleInstance(sys.argv[1],detect_legacy=False); assert s.acquire(); print('ready',flush=True); sys.stdin.read()"
    child = subprocess.Popen([sys.executable, "-c", code, name], cwd=ROOT,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    contender = SingleInstance(name, detect_legacy=False)
    try:
        assert child.stdout.readline().strip() == b"ready"
        assert not contender.acquire()
        child.kill()
        child.wait(timeout=10)
        # Windows can signal process termination just before finishing handle
        # table rundown. No application-side cleanup may be required.
        deadline = time.monotonic() + 2
        while not contender.acquire() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert contender._handle is not None
    finally:
        contender.close()
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


def test_default_name_uses_sid_and_not_installation_or_profile(monkeypatch):
    captured = []
    class Kernel:
        def CreateMutexW(self, _security, _owner, name):
            captured.append(name)
            return 1
        def CloseHandle(self, _handle):
            pass
    monkeypatch.setattr("utils.single_instance._kernel", lambda: Kernel())
    monkeypatch.setattr("utils.single_instance._process_identity", lambda _pid: ("S-1-5-21-test", 0))
    first = SingleInstance(detect_legacy=False)
    first.acquire()
    first.close()
    monkeypatch.setenv("APPDATA", "C:/different/profile")
    second = SingleInstance(detect_legacy=False)
    second.acquire()
    second.close()
    assert captured == ["Global\\WinWhisperPlus.Application.S-1-5-21-test"] * 2


def test_legacy_check_ignores_own_bootloader_other_users_and_newer_launches(monkeypatch):
    monkeypatch.setattr("utils.single_instance.os.getpid", lambda: 50)
    monkeypatch.setattr("utils.single_instance._processes", lambda: {
        50: ("winwhisperplus.exe", 40), 40: ("winwhisperplus.exe", 10),
        10: ("explorer.exe", 0), 20: ("winwhisperplus.exe", 10),
        60: ("winwhisperplus.exe", 10)})
    identities = {40: ("mine", 100), 20: ("other", 90), 60: ("mine", 110)}
    monkeypatch.setattr("utils.single_instance._process_identity", lambda pid: identities[pid])
    assert not _legacy_instance_running("mine")
    identities[20] = ("mine", 90)
    assert _legacy_instance_running("mine")


def test_legacy_exe_detected_from_another_directory(tmp_path):
    # A harmless renamed command processor stands in for an older frozen EXE.
    exe = tmp_path / "WinWhisperPlus.exe"
    shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32/cmd.exe", exe)
    child = subprocess.Popen([str(exe), "/d", "/c", "set /p wait="], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        code = "from utils.single_instance import _legacy_instance_running,_process_identity; import os; print(_legacy_instance_running(_process_identity(os.getpid())[0]))"
        probe = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=15)
        assert probe.returncode == 0, probe.stderr
        assert probe.stdout.strip() == "True"
    finally:
        child.kill()
        child.communicate(timeout=10)


def test_duplicate_start_shows_hint_before_settings_or_startup(qapp, monkeypatch):
    import main
    messages = []
    class Guard:
        def acquire(self): return False
        def close(self): pass
    monkeypatch.setattr(main, "SingleInstance", Guard)
    monkeypatch.setattr(main.sys, "argv", ["WinWhisperPlus.exe"])
    monkeypatch.setattr(main.QMessageBox, "information", lambda *args: messages.append(args[-1]))
    def forbidden(*_a, **_k):
        pytest.fail("Rejected startup must not load settings or application")
    monkeypatch.setattr(main, "Settings", forbidden)
    monkeypatch.setattr(main, "_run", forbidden)
    assert main.main() == 0
    assert len(messages) == 1 and "läuft bereits" in messages[0]


def test_startup_exception_releases_gate(qapp, monkeypatch):
    import main
    closed = []
    class Guard:
        def acquire(self): return True
        def close(self): closed.append(True)
    monkeypatch.setattr(main, "SingleInstance", Guard)
    monkeypatch.setattr(main.sys, "argv", ["WinWhisperPlus.exe"])
    def failure(_app):
        raise RuntimeError("startup failed")
    monkeypatch.setattr(main, "_run", failure)
    with pytest.raises(RuntimeError, match="startup failed"):
        main.main()
    assert closed == [True]


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_bundle_probe_exercises_real_startup_dependencies():
    from main import _check_instance_runtime
    _check_instance_runtime()


def test_bundle_probe_does_not_hide_missing_startup_dependency(monkeypatch):
    from main import _check_instance_runtime

    def unavailable(_pid):
        raise ModuleNotFoundError("No module named 'win32timezone'")

    monkeypatch.setattr("utils.single_instance._process_identity", unavailable)
    with pytest.raises(ModuleNotFoundError, match="win32timezone"):
        _check_instance_runtime()
