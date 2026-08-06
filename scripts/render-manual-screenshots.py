from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

import gui.settings_window as settings_window_module
from config.settings import Settings
from gui.history_window import HistoryWindow
from gui.settings_window import SettingsWindow
from gui.statistics_window import StatisticsWindow
from gui.status_window import StatusWindow


OUTPUT_DIR = ROOT / "docs" / "images" / "manual"
TEMP_APPDATA = ROOT / ".tmp_appdata_manual"


def _prepare_settings() -> Settings:
    if TEMP_APPDATA.exists():
        shutil.rmtree(TEMP_APPDATA)
    TEMP_APPDATA.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(TEMP_APPDATA)

    settings = Settings()
    settings.ui_language = "de"
    settings.language = "de"
    settings.hotkey_record = "ctrl+alt+h"
    settings.hotkey_language = "alt+shift+s"
    settings.microphone_index = 1
    settings.microphone_name = "Demo-Mikrofon"
    settings.live_whisper_model = "tiny"
    settings.final_whisper_model = "small"
    settings.auto_insert = True
    settings.live_transcription_enabled = True
    settings.emoji_mode_enabled = True
    settings.compute_device = "gpu:0"
    settings.keep_model_loaded = True
    return settings


def _save_widget(widget, filename: str, *, min_size: QSize | None = None) -> None:
    if min_size is not None:
        widget.resize(min_size)
    widget.show()
    widget.raise_()
    QApplication.processEvents()
    widget.grab().save(str(OUTPUT_DIR / filename))
    widget.close()


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    settings_window_module.list_microphones = lambda: [
        {"index": 1, "name": "Demo-Mikrofon"},
        {"index": 2, "name": "Headset-Mikrofon"},
    ]
    settings_window_module.app_version = lambda: "1.1"
    settings_window_module.list_vulkan_devices = lambda: [(0, "AMD Radeon 890M")]

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("WinWhisperPlus Manual Screenshots")
    QGuiApplication.setOverrideCursor(Qt.CursorShape.ArrowCursor)

    settings = _prepare_settings()

    status_ready = StatusWindow(hotkey_record=settings.hotkey_record, settings=settings)
    status_ready.set_status("ready")
    _save_widget(status_ready, "status-ready.png")

    status_recording = StatusWindow(hotkey_record=settings.hotkey_record, settings=settings)
    status_recording.set_status("recording")
    _save_widget(status_recording, "status-recording.png")

    settings_window = SettingsWindow(settings)
    _save_widget(settings_window, "settings.png", min_size=QSize(520, 640))

    history_window = HistoryWindow(settings=settings)
    history_window.set_history(
        [
            "Bitte den Termin für morgen bestätigen.",
            "Neue Aufgabe: Angebot prüfen und Rückmeldung senden.",
            "Das Protokoll ist fertig und kann versendet werden.",
        ]
    )
    _save_widget(history_window, "history.png", min_size=QSize(620, 420))

    statistics_window = StatisticsWindow(settings=settings)
    statistics_window.set_data(
        day_rows=[
            {"period": "2026-06-24", "count": 5, "total_seconds": 725.0, "avg_seconds": 145.0},
            {"period": "2026-06-23", "count": 3, "total_seconds": 420.0, "avg_seconds": 140.0},
        ],
        week_rows=[
            {"period": "2026-W26", "count": 18, "total_seconds": 2940.0, "avg_seconds": 163.3},
            {"period": "2026-W25", "count": 11, "total_seconds": 1515.0, "avg_seconds": 137.7},
        ],
        month_rows=[
            {"period": "2026-06", "count": 52, "total_seconds": 8340.0, "avg_seconds": 160.4},
        ],
    )
    _save_widget(statistics_window, "statistics.png", min_size=QSize(780, 540))

    print(f"Manual screenshots written to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
