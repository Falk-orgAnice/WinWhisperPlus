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
