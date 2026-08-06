"""
Settings management for WinWhisperPlus.
Persists configuration to a JSON file in the user's AppData directory.
"""

import json
import os
from pathlib import Path

DEFAULT_SETTINGS = {
    "hotkey_record": "ctrl+alt+h",
    "hotkey_language": "alt+shift+s",
    "language": "de",           # 'de', 'pl', 'en'
    "ui_language": "de",        # 'de', 'pl', 'en'
    "microphone_index": None,   # None = system default
    "microphone_name": None,    # Fallback when device indices change
    "whisper_model": "small",   # legacy alias for final_whisper_model
    "live_whisper_model": "tiny",
    "final_whisper_model": "small",
    # "auto" = default Vulkan GPU, "cpu" = CPU only, "gpu:<index>" = Vulkan device index
    "compute_device": "auto",
    "keep_model_loaded": False,
    "auto_insert": True,
    "live_transcription_enabled": False,
    "live_chunk_seconds": 2.0,
    "live_overlap_seconds": 0.5,
    "live_emit_min_interval_seconds": 1.0,
    "live_stable_window_seconds": 4.0,
    "window_position_x": None,  # x coordinate of status window
    "window_position_y": None,  # y coordinate of status window
    "emoji_mode_enabled": False,
}

LANGUAGES = {
    "de": "Deutsch",
    "pl": "Polski",
    "en": "English",
}

LANGUAGE_CYCLE = ["de", "pl", "en"]
UI_LANGUAGE_CYCLE = ["de", "pl", "en"]


def _config_path() -> Path:
    """Return path to the JSON settings file."""
    app_data = os.environ.get("APPDATA") or Path.home()
    config_dir = Path(app_data) / "WinWhisperPlus"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "settings.json"


def _legacy_config_path() -> Path:
    """Return the old MyWhisper settings path for backward-compatible loading."""
    app_data = os.environ.get("APPDATA") or Path.home()
    return Path(app_data) / "MyWhisper" / "settings.json"


class Settings:
    """Loads, holds and persists application settings."""

    def __init__(self) -> None:
        self._path = _config_path()
        self._data: dict = dict(DEFAULT_SETTINGS)
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        load_path = self._path if self._path.exists() else _legacy_config_path()
        if load_path.exists():
            try:
                with open(load_path, "r", encoding="utf-8") as fh:
                    stored = json.load(fh)
                if "final_whisper_model" not in stored and "whisper_model" in stored:
                    stored["final_whisper_model"] = stored["whisper_model"]
                # Merge with defaults so new keys are always present
                self._data.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
            except (json.JSONDecodeError, OSError):
                pass  # fall back to defaults

    def save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Property accessors
    # ------------------------------------------------------------------

    @property
    def hotkey_record(self) -> str:
        return self._data["hotkey_record"]

    @hotkey_record.setter
    def hotkey_record(self, value: str) -> None:
        self._data["hotkey_record"] = value

    @property
    def hotkey_language(self) -> str:
        return self._data["hotkey_language"]

    @hotkey_language.setter
    def hotkey_language(self, value: str) -> None:
        self._data["hotkey_language"] = value

    @property
    def language(self) -> str:
        return self._data["language"]

    @language.setter
    def language(self, value: str) -> None:
        if value in LANGUAGE_CYCLE:
            self._data["language"] = value

    @property
    def ui_language(self) -> str:
        return self._data["ui_language"]

    @ui_language.setter
    def ui_language(self, value: str) -> None:
        if value in UI_LANGUAGE_CYCLE:
            self._data["ui_language"] = value

    @property
    def microphone_index(self):
        return self._data["microphone_index"]

    @microphone_index.setter
    def microphone_index(self, value) -> None:
        self._data["microphone_index"] = value

    @property
    def microphone_name(self):
        return self._data["microphone_name"]

    @microphone_name.setter
    def microphone_name(self, value) -> None:
        self._data["microphone_name"] = value

    @property
    def window_position_x(self):
        return self._data["window_position_x"]

    @window_position_x.setter
    def window_position_x(self, value) -> None:
        self._data["window_position_x"] = value

    @property
    def window_position_y(self):
        return self._data["window_position_y"]

    @window_position_y.setter
    def window_position_y(self, value) -> None:
        self._data["window_position_y"] = value

    @property
    def whisper_model(self) -> str:
        return self.final_whisper_model

    @whisper_model.setter
    def whisper_model(self, value: str) -> None:
        self.final_whisper_model = value

    @property
    def live_whisper_model(self) -> str:
        return self._data["live_whisper_model"]

    @live_whisper_model.setter
    def live_whisper_model(self, value: str) -> None:
        self._data["live_whisper_model"] = value

    @property
    def final_whisper_model(self) -> str:
        return self._data["final_whisper_model"]

    @final_whisper_model.setter
    def final_whisper_model(self, value: str) -> None:
        self._data["final_whisper_model"] = value
        self._data["whisper_model"] = value

    @property
    def compute_device(self) -> str:
        return self._data["compute_device"]

    @compute_device.setter
    def compute_device(self, value: str) -> None:
        if value == "auto" or value == "cpu" or (
            isinstance(value, str) and value.startswith("gpu:") and value[4:].isdigit()
        ):
            self._data["compute_device"] = value

    @property
    def keep_model_loaded(self) -> bool:
        return bool(self._data["keep_model_loaded"])

    @keep_model_loaded.setter
    def keep_model_loaded(self, value: bool) -> None:
        self._data["keep_model_loaded"] = bool(value)

    @property
    def auto_insert(self) -> bool:
        return self._data["auto_insert"]

    @auto_insert.setter
    def auto_insert(self, value: bool) -> None:
        self._data["auto_insert"] = bool(value)

    @property
    def live_transcription_enabled(self) -> bool:
        return self._data["live_transcription_enabled"]

    @live_transcription_enabled.setter
    def live_transcription_enabled(self, value: bool) -> None:
        self._data["live_transcription_enabled"] = bool(value)

    @property
    def live_chunk_seconds(self) -> float:
        return float(self._data["live_chunk_seconds"])

    @property
    def live_overlap_seconds(self) -> float:
        return float(self._data["live_overlap_seconds"])

    @property
    def live_emit_min_interval_seconds(self) -> float:
        return float(self._data["live_emit_min_interval_seconds"])

    @property
    def live_stable_window_seconds(self) -> float:
        return float(self._data["live_stable_window_seconds"])

    @property
    def emoji_mode_enabled(self) -> bool:
        return bool(self._data["emoji_mode_enabled"])

    @emoji_mode_enabled.setter
    def emoji_mode_enabled(self, value: bool) -> None:
        self._data["emoji_mode_enabled"] = bool(value)

    def cycle_language(self) -> str:
        """Switch to the next language in the cycle and return its code."""
        idx = LANGUAGE_CYCLE.index(self.language)
        self.language = LANGUAGE_CYCLE[(idx + 1) % len(LANGUAGE_CYCLE)]
        return self.language
