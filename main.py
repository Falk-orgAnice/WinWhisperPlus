"""
MyWhisper – Entry point.

Usage:
    python main.py
"""

from __future__ import annotations

import sys
import json
import os
from pathlib import Path
from types import SimpleNamespace

# Only import lightweight modules here so the window can appear before
# the heavy modules (whisper, sounddevice, keyboard) are loaded.
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer

from config.localization import tr
from config.settings import Settings
from gui.status_window import StatusWindow
from utils.single_instance import SingleInstance


def _startup_ui_settings():
    # Read only the language before acquiring the instance gate. Constructing
    # Settings here would migrate/save configuration during a rejected start.
    try:
        path = Path(os.environ.get("APPDATA") or Path.home()) / "WinWhisperPlus/settings.json"
        language = json.loads(path.read_text(encoding="utf-8")).get("ui_language", "de")
        if not isinstance(language, str):
            language = "de"
    except (OSError, ValueError, AttributeError):
        language = "de"
    return SimpleNamespace(ui_language=language)


def main() -> int:
    qapp = QApplication.instance() or QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)  # keep running when windows are closed
    qapp.setApplicationName("WinWhisperPlus")
    qapp.setOrganizationName("WinWhisperPlus")
    # Isolated smoke tests never start hotkeys, model loading or an
    # interactive session, and must remain usable while the real app is open.
    if "--smoke-test" in sys.argv:
        return _run(qapp)
    guard = None
    try:
        guard = SingleInstance()
        if not guard.acquire():
            QMessageBox.information(None, "WinWhisperPlus", tr("already_running", _startup_ui_settings()))
            return 0
    except Exception as exc:
        if guard:
            guard.close()
        QMessageBox.critical(None, "WinWhisperPlus", tr("instance_check_failed", _startup_ui_settings()) + "\n" + str(exc))
        return 1
    try:
        return _run(qapp)
    finally:
        guard.close()


def _run(qapp) -> int:

    # Show the status window immediately with a loading indicator.
    # This makes the window appear (~200ms) before the heavy imports below.
    settings = Settings()
    status_window = StatusWindow(hotkey_record=settings.hotkey_record, settings=settings)
    status_window.load_position()
    status_window.set_loading(True, tr("initializing", settings))
    status_window.show()
    qapp.processEvents()  # Force Qt to paint the window NOW

    # Heavy imports happen here (whisper, sounddevice, keyboard ~2-3s).
    # The user already sees the window and loading spinner.
    from app import Application  # noqa: PLC0415

    application = Application(qapp, status_window=status_window, settings=settings)
    qapp.aboutToQuit.connect(application.shutdown)
    if "--smoke-test" in sys.argv:
        # Validate the frozen GUI and resources without recording, hotkeys or
        # multi-GB downloads. CI supplies isolated APPDATA/LOCALAPPDATA paths.
        from core.audio import find_ffmpeg
        from core.transcriber import Transcriber
        from core.text_optimizer import TextOptimizer
        from utils.resources import resource_path
        required = [find_ffmpeg(), Transcriber._find_executable(), TextOptimizer._find_executable(),
                    TextOptimizer._find_model(), resource_path("assets/model-catalog.json")]
        missing = [str(path) for path in required if not path.is_file()]
        try:
            _check_instance_runtime()
        except Exception as exc:
            missing.append(f"Single-instance startup check: {type(exc).__name__}: {exc}")
        (settings._path.parent / "bundle-smoke.txt").write_text("\n".join(missing) if missing else "OK", encoding="utf-8")
        QTimer.singleShot(1000, lambda: qapp.exit(1 if missing else 0))
    else:
        application.start()

    return qapp.exec()


def _check_instance_runtime():
    """Exercise the packaged Windows startup dependencies without blocking a live app."""
    import uuid
    from utils.single_instance import _legacy_instance_running, _process_identity

    sid, _ = _process_identity(os.getpid())
    # Exercise the legacy process scan as well; an existing app is fine here.
    _legacy_instance_running(sid)
    name = "Local\\WinWhisperPlus.Smoke." + uuid.uuid4().hex
    first = SingleInstance(name, detect_legacy=False)
    second = SingleInstance(name, detect_legacy=False)
    try:
        if not first.acquire() or second.acquire():
            raise RuntimeError("Instance gate did not reject a duplicate start")
        first.close()
        if not second.acquire():
            raise RuntimeError("Instance gate did not allow a restart")
    finally:
        first.close()
        second.close()


if __name__ == "__main__":
    sys.exit(main())
