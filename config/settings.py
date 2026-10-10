"""
Settings management for WinWhisperPlus.
Persists configuration to a JSON file in the user's AppData directory.
"""

import json
import os
import copy
import tempfile
from pathlib import Path

DEFAULT_SETTINGS = {
    "hotkey_record": "ctrl+alt+h",
    "hotkey_language": "alt+shift+s",
    "language": "de",           # 'de', 'pl', 'en', 'fr', 'nl'
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
    "text_optimization_enabled": False,
    "text_optimization_formatting_enabled": True,
    "text_optimization_cleanup_enabled": False,
    "text_optimization_redact_enabled": False,
    "text_translation_enabled": False,
    "text_translation_target_language": "en",
    "correction_rules_enabled": True,
    "correction_rules": [],
    "text_model": "bundled-qwen3-4b",
}

LANGUAGES = {
    "de": "Deutsch",
    "pl": "Polski",
    "en": "English",
    "fr": "Français",
    "nl": "Nederlands",
}

LANGUAGE_CYCLE = ["de", "pl", "en", "fr", "nl"]
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
        self._data: dict = copy.deepcopy(DEFAULT_SETTINGS)
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
                if not isinstance(stored, dict):
                    return
                if "final_whisper_model" not in stored and "whisper_model" in stored:
                    stored["final_whisper_model"] = stored["whisper_model"]
                # Migrate the former exclusive optimization profile to the
                # independently combinable options introduced in 1.1.4.
                if "text_optimization_profile" in stored and not any(
                    key in stored
                    for key in (
                        "text_optimization_formatting_enabled",
                        "text_optimization_cleanup_enabled",
                        "text_optimization_redact_enabled",
                    )
                ):
                    profile = stored["text_optimization_profile"]
                    stored["text_optimization_formatting_enabled"] = True
                    stored["text_optimization_cleanup_enabled"] = profile in {"cleanup", "redact"}
                    stored["text_optimization_redact_enabled"] = profile == "redact"
                # Merge with defaults so new keys are always present
                self._data.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
            except (json.JSONDecodeError, OSError):
                pass  # fall back to defaults

    def save(self) -> None:
        """Commit atomically; callers must surface persistence errors."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                                             prefix="settings-", suffix=".tmp", delete=False) as fh:
                temporary = Path(fh.name)
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, self._path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def snapshot(self) -> Settings:
        result = copy.copy(self)
        result._data = copy.deepcopy(self._data)
        return result

    @property
    def correction_rules_enabled(self) -> bool:
        return bool(self._data["correction_rules_enabled"])

    @correction_rules_enabled.setter
    def correction_rules_enabled(self, value: bool) -> None:
        self._data["correction_rules_enabled"] = bool(value)

    @property
    def correction_rules(self) -> list[dict]:
        from core.corrections import validate_rules
        try:
            return validate_rules(copy.deepcopy(self._data["correction_rules"]))
        except (ValueError, TypeError, AttributeError):
            return []

    @correction_rules.setter
    def correction_rules(self, value: list[dict]) -> None:
        from core.corrections import validate_rules
        self._data["correction_rules"] = validate_rules(value)

    @property
    def text_model(self) -> str:
        return self._data["text_model"]

    @text_model.setter
    def text_model(self, value: str) -> None:
        self._data["text_model"] = value

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

    @property
    def text_optimization_enabled(self) -> bool:
        return bool(self._data["text_optimization_enabled"])

    @text_optimization_enabled.setter
    def text_optimization_enabled(self, value: bool) -> None:
        self._data["text_optimization_enabled"] = bool(value)

    @property
    def text_optimization_formatting_enabled(self) -> bool:
        return bool(self._data["text_optimization_formatting_enabled"])

    @text_optimization_formatting_enabled.setter
    def text_optimization_formatting_enabled(self, value: bool) -> None:
        self._data["text_optimization_formatting_enabled"] = bool(value)

    @property
    def text_optimization_cleanup_enabled(self) -> bool:
        return bool(self._data["text_optimization_cleanup_enabled"])

    @text_optimization_cleanup_enabled.setter
    def text_optimization_cleanup_enabled(self, value: bool) -> None:
        self._data["text_optimization_cleanup_enabled"] = bool(value)

    @property
    def text_optimization_redact_enabled(self) -> bool:
        return bool(self._data["text_optimization_redact_enabled"])

    @text_optimization_redact_enabled.setter
    def text_optimization_redact_enabled(self, value: bool) -> None:
        self._data["text_optimization_redact_enabled"] = bool(value)

    @property
    def text_translation_enabled(self) -> bool:
        return bool(self._data["text_translation_enabled"])

    @text_translation_enabled.setter
    def text_translation_enabled(self, value: bool) -> None:
        self._data["text_translation_enabled"] = bool(value)

    @property
    def text_translation_target_language(self) -> str:
        return self._data["text_translation_target_language"]

    @text_translation_target_language.setter
    def text_translation_target_language(self, value: str) -> None:
        if value in LANGUAGE_CYCLE:
            self._data["text_translation_target_language"] = value

    def cycle_language(self) -> str:
        """Switch to the next language in the cycle and return its code."""
        idx = LANGUAGE_CYCLE.index(self.language)
        self.language = LANGUAGE_CYCLE[(idx + 1) % len(LANGUAGE_CYCLE)]
        return self.language
