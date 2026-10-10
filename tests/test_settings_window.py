from __future__ import annotations

import pytest

from PyQt6.QtWidgets import QApplication

from config.settings import Settings
from gui.settings_window import SettingsWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_settings_window_shows_version(qapp, monkeypatch):
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [(0, "AMD Radeon 890M")])
    monkeypatch.setattr("gui.settings_window.app_version", lambda: "9.8.7")

    window = SettingsWindow(Settings())

    assert window._version_label.text() == "Version: 9.8.7"

    window.close()


def test_settings_window_offers_cpu_and_detected_gpus(qapp, monkeypatch):
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [(0, "AMD Radeon 890M")])
    settings = Settings()
    settings.compute_device = "cpu"
    settings.keep_model_loaded = False

    window = SettingsWindow(settings)

    choices = [window._compute_combo.itemData(i) for i in range(window._compute_combo.count())]
    assert choices == ["auto", "cpu", "gpu:0"]
    assert window._compute_combo.currentData() == "cpu"
    assert window._keep_model_loaded_cb.isChecked() is False
    window.close()


def test_settings_window_persists_text_optimization(qapp, monkeypatch):
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [])
    settings = Settings()
    window = SettingsWindow(settings)

    window._text_optimization_cb.setChecked(True)
    window._text_cleanup_cb.setChecked(True)
    window._text_redact_cb.setChecked(True)
    window._text_translation_cb.setChecked(True)
    window._text_translation_target_combo.setCurrentIndex(1)
    window._save()

    assert settings.text_optimization_enabled is True
    assert settings.text_optimization_cleanup_enabled is True
    assert settings.text_optimization_redact_enabled is True
    assert settings.text_translation_enabled is True
    assert settings.text_translation_target_language == "pl"


def test_settings_window_offers_french_and_dutch_for_dictation_and_translation(qapp, monkeypatch):
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [])
    window = SettingsWindow(Settings())

    dictation_languages = [window._lang_combo.itemData(i) for i in range(window._lang_combo.count())]
    translation_languages = [
        window._text_translation_target_combo.itemData(i)
        for i in range(window._text_translation_target_combo.count())
    ]
    assert dictation_languages == ["de", "pl", "en", "fr", "nl"]
    assert translation_languages == dictation_languages
    window.close()


def test_cancel_does_not_modify_original_rules(qapp, monkeypatch):
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [])
    settings = Settings()
    settings.correction_rules = [{"source": "Organize", "target": "orgAnice"}]
    window = SettingsWindow(settings)
    window._rules_table.item(0, 2).setText("Changed")
    window.reject()
    assert settings.correction_rules[0]["target"] == "orgAnice"


def test_translation_can_be_enabled_without_text_optimization(qapp, monkeypatch):
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [])
    window = SettingsWindow(Settings())
    window._text_optimization_cb.setChecked(False)
    window._text_translation_cb.setChecked(True)
    assert window._text_translation_cb.isEnabled()
    assert window._text_translation_target_combo.isEnabled()
    window.close()
