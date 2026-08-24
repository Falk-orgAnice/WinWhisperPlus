from __future__ import annotations

import pytest

from PyQt6.QtWidgets import QApplication

from config.settings import Settings
from gui.status_window import StatusWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_default_state_shows_hotkey_not_progress(qapp):
    window = StatusWindow(hotkey_record="ctrl+alt+h")

    assert not window._hotkey_label.isHidden()
    assert window._hotkey_label.text() == "Ctrl+Alt+H"
    assert window._progress_bar.isHidden()
    assert window._label.wordWrap()
    assert window.width() == 130
    assert window.height() == 60

    window.close()


def test_loading_state_shows_progress_not_hotkey(qapp):
    window = StatusWindow(hotkey_record="ctrl+alt+h")

    window.set_loading(True, "Modelle laden...")

    assert not window._progress_bar.isHidden()
    assert window._hotkey_label.isHidden()
    assert window._label.text() == "Modelle laden..."

    window.close()


def test_loading_off_restores_status_and_hotkey(qapp):
    window = StatusWindow(hotkey_record="ctrl+alt+h")

    window.set_status("ready")
    window.set_loading(True, "Modelle laden...")
    window.set_loading(False)

    assert window._label.text() == "Bereit"
    assert not window._hotkey_label.isHidden()
    assert window._progress_bar.isHidden()

    window.close()


def test_message_clear_while_loading_restores_loading_text(qapp):
    window = StatusWindow(hotkey_record="ctrl+alt+h")

    window.set_loading(True, "Modelle laden...")
    window.show_message("Kurzmeldung", duration_ms=1)
    window._clear_message()

    assert window._label.text() == "Modelle laden..."
    assert not window._progress_bar.isHidden()
    assert window._hotkey_label.isHidden()

    window.close()


def test_english_ui_translates_status_and_hotkey_label(qapp):
    settings = Settings()
    settings.ui_language = "en"
    window = StatusWindow(hotkey_record="ctrl+alt+h", settings=settings)
    window.set_status("ready")

    assert window._label.text() == "Ready"
    assert window._hotkey_label.text() == "Ctrl+Alt+H"

    window.close()


def test_recovery_action_is_disabled_without_a_saved_recording(qapp):
    window = StatusWindow(hotkey_record="ctrl+alt+h")

    menu = window._build_context_menu()
    retry_action = next(action for action in menu.actions() if "Gesicherte Aufnahme" in action.text())
    assert not retry_action.isEnabled()

    window.set_retry_failed_transcription_available(True)
    menu = window._build_context_menu()
    retry_action = next(action for action in menu.actions() if "Gesicherte Aufnahme" in action.text())
    assert retry_action.isEnabled()

    window.close()
