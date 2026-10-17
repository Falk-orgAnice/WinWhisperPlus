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
    settings.save_rules()
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


@pytest.fixture
def rules_window(qapp, monkeypatch):
    from core.rule_store import RuleStore
    monkeypatch.setattr("gui.settings_window.list_microphones", lambda: [])
    monkeypatch.setattr("gui.settings_window.list_vulkan_devices", lambda: [])
    settings = Settings()
    settings.correction_rules = [{"enabled": True, "source": "Organize", "target": "orgAnice"}]
    settings.save_rules()
    settings.save()
    window = SettingsWindow(settings)
    yield settings, window
    window.close()


def test_path_preview_and_cancel_leave_files_and_settings_unchanged(rules_window, tmp_path):
    from core.rule_store import RuleStore
    settings, window = rules_window
    old_path = settings.correction_rules_path
    other = tmp_path / "existing.json"
    RuleStore(other).save([])
    window._rules_path_edit.setText(str(other))
    assert window._change_rules_path()
    assert window._rules_table.rowCount() == 0
    new = tmp_path / "not-yet-created/names.json"
    window._rules_path_edit.setText(str(new))
    assert window._change_rules_path()
    window.reject()
    assert settings.correction_rules_path == old_path
    assert settings.correction_rules[0]["target"] == "orgAnice"
    assert not new.parent.exists()


def test_new_path_copies_rules_and_persists_choice(rules_window, tmp_path):
    from core.rule_store import RuleStore
    settings, window = rules_window
    old = settings.correction_rules_path
    original = old.read_bytes()
    new = tmp_path / "new/location.json"
    window._rules_path_edit.setText(str(new))
    window._save()
    assert settings.correction_rules_path == new
    assert old.read_bytes() == original
    assert RuleStore(new).load()[0] == settings.correction_rules
    assert Settings().correction_rules_path == new


def test_dirty_path_switch_needs_confirmation(rules_window, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    settings, window = rules_window
    window._rules_table.item(0, 2).setText("Edited")
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.No)
    window._rules_path_edit.setText(str(tmp_path / "other.json"))
    assert not window._change_rules_path()
    assert window._rules_table.item(0, 2).text() == "Edited"
    assert window._rules_path_edit.text() == str(settings.correction_rules_path)


def test_external_changes_require_confirmation_or_reload(rules_window, monkeypatch):
    from core.rule_store import RuleStore
    from PyQt6.QtWidgets import QMessageBox
    settings, window = rules_window
    RuleStore(settings.correction_rules_path).save([])
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.No)
    window._save()
    assert RuleStore(settings.correction_rules_path).load()[0] == []
    assert window.result() != window.DialogCode.Accepted
    window._reload_rules()
    assert window._rules_table.rowCount() == 0


def test_explicit_conflict_confirmation_allows_overwrite(rules_window, monkeypatch):
    from core.rule_store import RuleStore
    from PyQt6.QtWidgets import QMessageBox
    settings, window = rules_window
    RuleStore(settings.correction_rules_path).save([])
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    window._save()
    assert RuleStore(settings.correction_rules_path).load()[0][0]["target"] == "orgAnice"


def test_failed_path_save_keeps_previous_active_path(rules_window, tmp_path, monkeypatch):
    from core.rule_store import RuleStore, RulesFileError
    from PyQt6.QtWidgets import QMessageBox
    settings, window = rules_window
    old = settings.correction_rules_path
    window._rules_path_edit.setText(str(tmp_path / "unwritable.json"))
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: messages.append(_args[-1]))
    def fail(self, *_a, **_k):
        raise RulesFileError(self.path, "rules_write_failed", "permission denied")
    monkeypatch.setattr(RuleStore, "save", fail)
    window._save()
    assert settings.correction_rules_path == old
    assert messages and "permission denied" in messages[0]


def test_explorer_button_uses_selected_path_without_creating_it(rules_window, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    settings, window = rules_window
    called = []
    monkeypatch.setattr("gui.settings_window.reveal_file", lambda path: called.append(path))
    window._rules_reveal_button.click()
    assert called == [settings.correction_rules_path]
    assert window._rules_reveal_button.toolTip() == "Datei im Explorer anzeigen"
    assert window._rules_reveal_button.text() == ""
