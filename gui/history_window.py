"""
History window showing recently recognized texts.
Allows user to view and re-insert previous transcriptions.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel
)

from config.localization import tr


class HistoryWindow(QDialog):
    """Modal dialog showing transcription history."""

    text_selected = pyqtSignal(str)  # Emitted when user selects a text to re-insert

    def __init__(self, parent: QWidget | None = None, settings=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(tr("history_title", self._settings))
        self.setGeometry(100, 100, 600, 400)
        
        layout = QVBoxLayout(self)
        
        # Title
        self._title = QLabel()
        layout.addWidget(self._title)
        
        # History list
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_selected)
        layout.addWidget(self._list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self._insert_btn = QPushButton()
        self._insert_btn.clicked.connect(self._on_insert)
        self._insert_btn.setEnabled(False)
        button_layout.addWidget(self._insert_btn)

        self._copy_btn = QPushButton()
        self._copy_btn.clicked.connect(self._on_copy)
        self._copy_btn.setEnabled(False)
        button_layout.addWidget(self._copy_btn)

        self._close_btn = QPushButton()
        self._close_btn.clicked.connect(self.close)
        button_layout.addWidget(self._close_btn)
        
        layout.addLayout(button_layout)
        
        # Connect selection changes
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self._list)
        self._copy_shortcut.activated.connect(self._on_copy)
        self.retranslate_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_history(self, history: list[str]) -> None:
        """Update the history list display."""
        self._list.clear()
        for text in reversed(history):  # Show most recent first
            if text.strip():  # Only add non-empty texts
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, text)
                self._list.addItem(item)

    def retranslate_ui(self) -> None:
        """Refresh UI strings for the current interface language."""
        self.setWindowTitle(tr("history_title", self._settings))
        self._title.setText(tr("history_header", self._settings))
        self._insert_btn.setText(tr("insert", self._settings))
        self._copy_btn.setText(tr("copy", self._settings))
        self._close_btn.setText(tr("close", self._settings))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        """Enable actions when something is selected."""
        has_selection = len(self._list.selectedItems()) > 0
        self._insert_btn.setEnabled(has_selection)
        self._copy_btn.setEnabled(has_selection)

    def _on_item_selected(self) -> None:
        """Handle double-click on history item."""
        self._on_insert()

    def _on_insert(self) -> None:
        """Emit selected text and close dialog."""
        selected = self._list.selectedItems()
        if selected:
            text = selected[0].text()
            self.text_selected.emit(text)
            self.close()

    def _on_copy(self) -> None:
        """Copy the selected history entry without closing the dialog."""
        selected = self._list.selectedItems()
        if selected:
            QGuiApplication.clipboard().setText(selected[0].text())
