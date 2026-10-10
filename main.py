"""
MyWhisper – Entry point.

Usage:
    python main.py
"""

from __future__ import annotations

import sys

# Only import lightweight modules here so the window can appear before
# the heavy modules (whisper, sounddevice, keyboard) are loaded.
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from config.localization import tr
from config.settings import Settings
from gui.status_window import StatusWindow


def main() -> None:
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)  # keep running when windows are closed
    qapp.setApplicationName("MyWhisper")
    qapp.setOrganizationName("MyWhisper")

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
        (settings._path.parent / "bundle-smoke.txt").write_text("\n".join(missing) if missing else "OK", encoding="utf-8")
        QTimer.singleShot(1000, lambda: qapp.exit(1 if missing else 0))
    else:
        application.start()

    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
