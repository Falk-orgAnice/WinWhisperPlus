from __future__ import annotations

import pytest

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from gui.history_window import HistoryWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_copy_button_is_enabled_only_with_a_selected_entry(qapp):
    window = HistoryWindow()
    window.set_history(["Erster Eintrag"])

    assert not window._copy_btn.isEnabled()

    window._list.setCurrentRow(0)

    assert window._copy_btn.isEnabled()
    window.close()


def test_copy_button_copies_selected_entry_without_closing(qapp):
    window = HistoryWindow()
    window.set_history(["In die Zwischenablage"])
    window.show()
    window._list.setCurrentRow(0)

    window._copy_btn.click()

    assert QGuiApplication.clipboard().text() == "In die Zwischenablage"
    assert window.isVisible()
    window.close()


def test_ctrl_c_copies_selected_entry_when_history_list_has_focus(qapp):
    window = HistoryWindow()
    window.set_history(["Kopieren mit Tastatur"])
    window.show()
    window._list.setCurrentRow(0)
    window._list.setFocus()

    QTest.keyClick(window._list, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    assert QGuiApplication.clipboard().text() == "Kopieren mit Tastatur"
    assert window.isVisible()
    window.close()


def test_double_click_keeps_existing_insert_behavior(qapp):
    window = HistoryWindow()
    window.set_history(["Erneut einfügen"])
    selected_texts: list[str] = []
    window.text_selected.connect(selected_texts.append)
    window.show()
    window._list.setCurrentRow(0)

    window._list.itemDoubleClicked.emit(window._list.item(0))

    assert selected_texts == ["Erneut einfügen"]
    assert not window.isVisible()
