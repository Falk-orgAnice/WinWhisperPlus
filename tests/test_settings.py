"""Tests for config/settings.py"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Patch the config path to use a temp directory for all tests
@pytest.fixture(autouse=True)
def temp_config(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield tmp_path


def _make_settings():
    from config.settings import Settings
    return Settings()


def test_default_settings():
    s = _make_settings()
    assert s.hotkey_record == "ctrl+alt+h"
    assert s.hotkey_language == "alt+shift+s"
    assert s.language == "de"
    assert s.ui_language == "de"
    assert s.microphone_index is None
    assert s.microphone_name is None
    assert s.whisper_model == "small"
    assert s.live_whisper_model == "tiny"
    assert s.final_whisper_model == "small"
    assert s.compute_device == "auto"
    assert s.keep_model_loaded is False
    assert s.auto_insert is True
    assert s.live_transcription_enabled is False
    assert s.text_optimization_enabled is False
    assert s.text_optimization_formatting_enabled is True
    assert s.text_optimization_cleanup_enabled is False
    assert s.text_optimization_redact_enabled is False
    assert s.text_translation_enabled is False
    assert s.text_translation_target_language == "en"


def test_save_and_reload(tmp_path):
    s = _make_settings()
    s.language = "pl"
    s.ui_language = "en"
    s.hotkey_record = "ctrl+shift+r"
    s.microphone_index = 2
    s.microphone_name = "USB Microphone"
    s.save()

    s2 = _make_settings()
    assert s2.language == "pl"
    assert s2.ui_language == "en"
    assert s2.hotkey_record == "ctrl+shift+r"
    assert s2.microphone_index == 2
    assert s2.microphone_name == "USB Microphone"


def test_cycle_language():
    s = _make_settings()
    assert s.language == "de"
    lang = s.cycle_language()
    assert lang == "pl"
    lang = s.cycle_language()
    assert lang == "en"
    lang = s.cycle_language()
    assert lang == "fr"
    lang = s.cycle_language()
    assert lang == "nl"
    lang = s.cycle_language()
    assert lang == "de"


def test_invalid_language_ignored():
    s = _make_settings()
    s.language = "xx"
    assert s.language == "de"  # unchanged


def test_invalid_ui_language_ignored():
    s = _make_settings()
    s.ui_language = "xx"
    assert s.ui_language == "de"


def test_corrupted_json_falls_back_to_defaults(tmp_path):
    config_dir = tmp_path / "MyWhisper"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text("not-valid-json")
    s = _make_settings()
    assert s.hotkey_record == "ctrl+alt+h"


def test_partial_json_merges_with_defaults(tmp_path):
    config_dir = tmp_path / "MyWhisper"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({"language": "en"}))
    s = _make_settings()
    assert s.language == "en"
    assert s.hotkey_record == "ctrl+alt+h"  # default preserved


def test_live_transcription_setting_persists():
    s = _make_settings()
    s.live_transcription_enabled = True
    s.save()

    s2 = _make_settings()
    assert s2.live_transcription_enabled is True


def test_dual_model_settings_persist() -> None:
    s = _make_settings()
    s.live_whisper_model = "base"
    s.final_whisper_model = "small"
    s.save()

    s2 = _make_settings()
    assert s2.live_whisper_model == "base"
    assert s2.final_whisper_model == "small"
    assert s2.whisper_model == "small"


def test_compute_device_persists_and_rejects_invalid_values() -> None:
    s = _make_settings()
    s.compute_device = "gpu:1"
    s.save()

    s2 = _make_settings()
    assert s2.compute_device == "gpu:1"
    s2.compute_device = "invalid"
    assert s2.compute_device == "gpu:1"


def test_keep_model_loaded_persists() -> None:
    s = _make_settings()
    s.keep_model_loaded = True
    s.save()

    assert _make_settings().keep_model_loaded is True


def test_text_optimization_settings_persist_and_reject_invalid_translation_language() -> None:
    s = _make_settings()
    s.text_optimization_enabled = True
    s.text_optimization_formatting_enabled = True
    s.text_optimization_cleanup_enabled = True
    s.text_optimization_redact_enabled = True
    s.text_translation_enabled = True
    s.text_translation_target_language = "pl"
    s.save()

    s2 = _make_settings()
    assert s2.text_optimization_enabled is True
    assert s2.text_optimization_cleanup_enabled is True
    assert s2.text_optimization_redact_enabled is True
    assert s2.text_translation_enabled is True
    assert s2.text_translation_target_language == "pl"
    s2.text_translation_target_language = "invalid"
    assert s2.text_translation_target_language == "pl"


def test_legacy_text_optimization_profile_migrates_to_combined_options(tmp_path) -> None:
    config_dir = tmp_path / "MyWhisper"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({"text_optimization_profile": "redact"}))

    s = _make_settings()

    assert s.text_optimization_formatting_enabled is True
    assert s.text_optimization_cleanup_enabled is True
    assert s.text_optimization_redact_enabled is True


def test_legacy_whisper_model_migrates_to_final(tmp_path) -> None:
    config_dir = tmp_path / "MyWhisper"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps({"whisper_model": "medium"}))

    s = _make_settings()

    assert s.final_whisper_model == "medium"
    assert s.whisper_model == "medium"


def test_failed_atomic_save_keeps_previous_json(monkeypatch):
    s = _make_settings()
    s.save()
    previous = s._path.read_bytes()
    s.language = "en"
    def failed_replace(*_args):
        raise OSError("disk failure")
    monkeypatch.setattr("config.settings.os.replace", failed_replace)
    with pytest.raises(OSError):
        s.save()
    assert s._path.read_bytes() == previous
    assert not list(s._path.parent.glob("settings-*.tmp"))
