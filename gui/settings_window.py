"""
Settings window – allows the user to configure hotkeys, language,
microphone and Whisper model size.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView,
    QFileDialog, QToolButton, QStyle,
)
from PyQt6.QtGui import QKeySequence

from config.localization import UI_LANGUAGES, localized_spoken_language_name, tr
from config.settings import LANGUAGE_CYCLE, UI_LANGUAGE_CYCLE, Settings
from core.recorder import list_microphones
from core.transcriber import COMPUTE_DEVICE_AUTO, COMPUTE_DEVICE_CPU, list_vulkan_devices
from utils.resources import app_version
from utils.explorer import reveal_file
from core.rule_store import RuleStore, RulesFileError, RulesConflict

if TYPE_CHECKING:
    pass

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large", "large-v3-turbo", "large-v3-turbo-q5_0"]


class HotkeyEdit(QLineEdit):
    """Single-line editor that captures a key combination."""

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        # The parent's keyPressEvent signature uses QKeyEvent; we accept the
        # generic QEvent type here so the override works with PyQt6's type stubs.
        mods = event.modifiers()
        key = event.key()

        parts = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("win")

        ignore = {
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Shift,
            Qt.Key.Key_Meta,
        }
        if key not in ignore:
            seq = QKeySequence(key).toString().lower()
            if seq:
                parts.append(seq)

        if parts:
            self.setText("+".join(parts))


class SettingsWindow(QDialog):
    """Modal settings dialog."""

    settings_saved = pyqtSignal(Settings)

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        settings.refresh_rules()
        self._settings = settings
        self._original_settings = settings
        self._settings = settings.snapshot()
        self.setWindowTitle(tr("settings_title", self._settings))
        self.setMinimumWidth(620)
        self.resize(780, 680)
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)
        general = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(general)
        self._tabs.addTab(scroll, tr("general", self._settings))
        content = QVBoxLayout(general)

        # --- Hotkeys ---------------------------------------------------
        self._hk_group = QGroupBox()
        hk_form = QFormLayout(self._hk_group)
        self._hk_form = hk_form

        self._hk_record = HotkeyEdit()
        hk_form.addRow("", self._hk_record)

        self._hk_lang = HotkeyEdit()
        hk_form.addRow("", self._hk_lang)
        content.addWidget(self._hk_group)

        # --- Language --------------------------------------------------
        self._lang_group = QGroupBox()
        lang_layout = QHBoxLayout(self._lang_group)
        self._lang_combo = QComboBox()
        lang_layout.addWidget(self._lang_combo)
        content.addWidget(self._lang_group)

        self._ui_lang_group = QGroupBox()
        ui_lang_layout = QHBoxLayout(self._ui_lang_group)
        self._ui_lang_combo = QComboBox()
        ui_lang_layout.addWidget(self._ui_lang_combo)
        content.addWidget(self._ui_lang_group)

        # --- Microphone ------------------------------------------------
        self._mic_group = QGroupBox()
        mic_layout = QHBoxLayout(self._mic_group)
        self._mic_combo = QComboBox()
        mic_layout.addWidget(self._mic_combo)
        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setFixedWidth(30)
        self._refresh_btn.clicked.connect(self._refresh_mics)
        mic_layout.addWidget(self._refresh_btn)
        content.addWidget(self._mic_group)

        # --- Models ----------------------------------------------------
        self._model_group = QGroupBox()
        model_layout = QVBoxLayout(self._model_group)

        live_row = QHBoxLayout()
        self._live_model_label = QLabel()
        live_row.addWidget(self._live_model_label)
        self._live_model_combo = QComboBox()
        for m in ["tiny", "base"]:
            self._live_model_combo.addItem(m)
        live_row.addWidget(self._live_model_combo)
        model_layout.addLayout(live_row)

        final_row = QHBoxLayout()
        self._final_model_label = QLabel()
        final_row.addWidget(self._final_model_label)
        self._final_model_combo = QComboBox()
        for m in WHISPER_MODELS:
            self._final_model_combo.addItem(m)
        final_row.addWidget(self._final_model_combo)
        model_layout.addLayout(final_row)

        self._model_note = QLabel()
        model_layout.addWidget(self._model_note)
        self._model_page = QWidget()
        self._model_layout = QVBoxLayout(self._model_page)
        self._model_layout.addWidget(self._model_group)
        self._tabs.addTab(self._model_page, tr("models", self._settings))

        # --- Compute device -------------------------------------------
        self._compute_group = QGroupBox()
        compute_layout = QHBoxLayout(self._compute_group)
        self._compute_label = QLabel()
        compute_layout.addWidget(self._compute_label)
        self._compute_combo = QComboBox()
        compute_layout.addWidget(self._compute_combo)
        self._model_layout.addWidget(self._compute_group)
        self._keep_model_loaded_cb = QCheckBox()
        self._model_layout.addWidget(self._keep_model_loaded_cb)
        text_model_row = QHBoxLayout()
        text_model_row.addWidget(QLabel(tr("text_model", self._settings)))
        self._text_model_combo = QComboBox()
        text_model_row.addWidget(self._text_model_combo)
        self._model_layout.addLayout(text_model_row)
        from gui.model_manager import ModelManagerWidget
        self._model_manager = ModelManagerWidget(self._settings, self)
        self._model_manager.changed.connect(self._refresh_text_models)
        self._model_layout.addWidget(self._model_manager)
        self._refresh_text_models()

        # --- Auto insert -----------------------------------------------
        self._auto_insert_cb = QCheckBox()
        content.addWidget(self._auto_insert_cb)

        self._live_transcription_cb = QCheckBox()
        content.addWidget(self._live_transcription_cb)

        self._emoji_mode_cb = QCheckBox()
        content.addWidget(self._emoji_mode_cb)

        # --- Local text optimization ---------------------------------
        self._text_optimization_group = QGroupBox()
        text_optimization_layout = QVBoxLayout(self._text_optimization_group)
        self._text_optimization_cb = QCheckBox()
        self._text_optimization_cb.toggled.connect(self._update_text_optimization_controls)
        text_optimization_layout.addWidget(self._text_optimization_cb)
        self._text_formatting_cb = QCheckBox()
        text_optimization_layout.addWidget(self._text_formatting_cb)
        self._text_cleanup_cb = QCheckBox()
        text_optimization_layout.addWidget(self._text_cleanup_cb)
        self._text_redact_cb = QCheckBox()
        text_optimization_layout.addWidget(self._text_redact_cb)
        self._text_translation_cb = QCheckBox()
        self._text_translation_cb.toggled.connect(self._update_text_optimization_controls)
        text_optimization_layout.addWidget(self._text_translation_cb)
        translation_row = QHBoxLayout()
        self._text_translation_target_label = QLabel()
        translation_row.addWidget(self._text_translation_target_label)
        self._text_translation_target_combo = QComboBox()
        for code in LANGUAGE_CYCLE:
            self._text_translation_target_combo.addItem("", code)
        translation_row.addWidget(self._text_translation_target_combo)
        text_optimization_layout.addLayout(translation_row)
        self._text_optimization_note = QLabel()
        self._text_optimization_note.setWordWrap(True)
        text_optimization_layout.addWidget(self._text_optimization_note)
        content.addWidget(self._text_optimization_group)
        self._build_corrections()

        # --- Buttons ---------------------------------------------------
        btn_layout = QHBoxLayout()
        self._version_label = QLabel()
        btn_layout.addWidget(self._version_label)
        self._save_btn = QPushButton()
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self._save)
        self._cancel_btn = QPushButton()
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._cancel_btn)
        root.addLayout(btn_layout)
        self.retranslate_ui()

    def _build_corrections(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._rules_enabled = QCheckBox(tr("correction_enabled", self._settings))
        self._rules_enabled.setChecked(self._settings.correction_rules_enabled)
        layout.addWidget(self._rules_enabled)
        path_row = QHBoxLayout()
        self._rules_path_label = QLabel(tr("rules_file", self._settings))
        path_row.addWidget(self._rules_path_label)
        self._rules_path = self._settings.correction_rules_path
        self._rules_path_edit = QLineEdit(str(self._rules_path))
        self._rules_path_edit.setToolTip(str(self._rules_path))
        self._rules_path_edit.setMinimumWidth(100)
        self._rules_path_edit.editingFinished.connect(self._change_rules_path)
        path_row.addWidget(self._rules_path_edit, 1)
        browse = QToolButton()
        browse.setText("…")
        browse.setToolTip(tr("rules_file_choose", self._settings))
        browse.setAccessibleName(tr("rules_file_choose", self._settings))
        browse.clicked.connect(self._browse_rules)
        path_row.addWidget(browse)
        self._rules_reveal_button = QToolButton()
        self._rules_reveal_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._rules_reveal_button.setToolTip(tr("rules_reveal", self._settings))
        self._rules_reveal_button.setAccessibleName(tr("rules_reveal", self._settings))
        self._rules_reveal_button.clicked.connect(self._reveal_rules)
        path_row.addWidget(self._rules_reveal_button)
        layout.addLayout(path_row)
        self._rules_error = QLabel()
        self._rules_error.setWordWrap(True)
        self._rules_error.setText(self._rules_error_text(self._settings.rules_error) if self._settings.rules_error else "")
        layout.addWidget(self._rules_error)
        self._rules_table = QTableWidget(0, 3)
        self._rules_table.setHorizontalHeaderLabels([tr(k, self._settings) for k in ("active", "recognized", "replacement")])
        header = self._rules_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._rules_table)
        buttons = QHBoxLayout()
        add = QPushButton(tr("add", self._settings))
        add.clicked.connect(lambda: self._add_rule())
        remove = QPushButton(tr("delete", self._settings))
        remove.clicked.connect(self._remove_rules)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        reload_button = QPushButton(tr("rules_reload", self._settings))
        reload_button.clicked.connect(self._reload_rules)
        buttons.addWidget(reload_button)
        layout.addLayout(buttons)
        note = QLabel(tr("correction_note", self._settings))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._tabs.addTab(page, tr("correction_rules", self._settings))
        for rule in self._settings.correction_rules:
            self._add_rule(rule)
        self._rules_baseline = self._table_rules()
        self._rules_revision = self._settings._rules_revision

    def _rules_error_text(self, error):
        return tr(error.key, self._settings) + "\n" + str(error.path) + ("\n" + error.detail if error.detail else "")

    def _table_rules(self):
        return [{"source": self._rules_table.item(row, 1).text(),
                 "target": self._rules_table.item(row, 2).text(),
                 "enabled": self._rules_table.item(row, 0).checkState() == Qt.CheckState.Checked}
                for row in range(self._rules_table.rowCount())]

    def _confirm_discard(self, *, copy=False):
        return self._table_rules() == self._rules_baseline or QMessageBox.question(
            self, tr("correction_rules", self._settings), tr("rules_copy_unsaved" if copy else "rules_discard", self._settings),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _change_rules_path(self, *, reload=False):
        try:
            path = self._settings.resolve_rules_path(self._rules_path_edit.text().strip())
            if path == self._settings._path:
                raise RulesFileError(path, "rules_invalid_path")
            if path == self._rules_path and not reload:
                self._rules_path_edit.setText(str(path))
                self._rules_path_edit.setToolTip(str(path))
                return True
            if not self._confirm_discard(copy=not path.exists() and not reload):
                self._rules_path_edit.setText(str(self._rules_path))
                return False
            rules, revision = RuleStore(path).load() if path.exists() or reload else (self._table_rules(), None)
            self._rules_table.setRowCount(0)
            for rule in rules:
                self._add_rule(rule)
            self._rules_path, self._rules_revision = path, revision
            self._rules_path_edit.setText(str(path))
            self._rules_path_edit.setToolTip(str(path))
            self._rules_baseline = self._table_rules()
            self._rules_error.clear()
            return True
        except RulesFileError as exc:
            self._rules_path_edit.setText(str(self._rules_path))
            QMessageBox.warning(self, tr("correction_rules", self._settings), self._rules_error_text(exc))
            return False

    def _browse_rules(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("rules_file_choose", self._settings),
                                             str(self._rules_path), "JSON (*.json);;All files (*)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self._rules_path_edit.setText(path)
            self._change_rules_path()

    def _reload_rules(self):
        self._change_rules_path(reload=True)

    def _reveal_rules(self):
        if not self._change_rules_path():
            return
        try:
            reveal_file(self._rules_path)
        except OSError as exc:
            QMessageBox.warning(self, tr("rules_reveal", self._settings), tr("rules_parent_missing", self._settings) + "\n" + str(exc))

    def _add_rule(self, rule=None) -> None:
        rule = rule or {"source": "", "target": "", "enabled": True}
        row = self._rules_table.rowCount()
        self._rules_table.insertRow(row)
        self._rules_table.setItem(row, 1, QTableWidgetItem(rule["source"]))
        self._rules_table.setItem(row, 2, QTableWidgetItem(rule["target"]))
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if rule["enabled"] else Qt.CheckState.Unchecked)
        self._rules_table.setItem(row, 0, item)

    def _remove_rules(self) -> None:
        for row in sorted({i.row() for i in self._rules_table.selectedIndexes()}, reverse=True):
            self._rules_table.removeRow(row)

    def _refresh_text_models(self):
        selected = self._text_model_combo.currentData() or self._settings.text_model
        self._text_model_combo.clear()
        for model in self._model_manager.manager.catalog.values():
            if model.kind == "text":
                self._text_model_combo.addItem(model.name, model.id)
            elif model.kind == "speech" and model.id != "large-v3" and self._final_model_combo.findText(model.id) < 0:
                self._final_model_combo.addItem(model.id)
        if self._text_model_combo.findData(selected) < 0:
            self._text_model_combo.addItem(selected, selected)
        self._text_model_combo.setCurrentIndex(self._text_model_combo.findData(selected))

    def done(self, result):
        if hasattr(self, "_model_manager"):
            self._model_manager.stop()
        super().done(result)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def retranslate_ui(self) -> None:
        """Refresh UI strings for the current interface language."""
        self.setWindowTitle(tr("settings_title", self._settings))
        self._hk_group.setTitle(tr("group_hotkeys", self._settings))
        self._hk_record.setToolTip(tr("tooltip_press_hotkey", self._settings))
        self._hk_lang.setToolTip(tr("tooltip_press_hotkey", self._settings))
        self._hk_form.setWidget(0, QFormLayout.ItemRole.LabelRole, QLabel(tr("hotkey_record", self._settings)))
        self._hk_form.setWidget(1, QFormLayout.ItemRole.LabelRole, QLabel(tr("hotkey_language", self._settings)))
        self._lang_group.setTitle(tr("group_language", self._settings))
        self._ui_lang_group.setTitle(tr("group_ui_language", self._settings))
        self._mic_group.setTitle(tr("group_microphone", self._settings))
        self._refresh_btn.setToolTip(tr("refresh_devices", self._settings))
        self._model_group.setTitle(tr("group_models", self._settings))
        self._live_model_label.setText(tr("live_model", self._settings))
        self._final_model_label.setText(tr("final_model", self._settings))
        self._model_note.setText(tr("model_note", self._settings))
        self._compute_group.setTitle(tr("group_compute", self._settings))
        self._compute_label.setText(tr("compute_device", self._settings))
        self._keep_model_loaded_cb.setText(tr("keep_model_loaded", self._settings))
        self._keep_model_loaded_cb.setToolTip(tr("keep_model_loaded_tooltip", self._settings))
        self._auto_insert_cb.setText(tr("auto_insert", self._settings))
        self._live_transcription_cb.setText(tr("live_transcription", self._settings))
        self._live_transcription_cb.setToolTip(tr("live_transcription_tooltip", self._settings))
        self._emoji_mode_cb.setText(tr("emoji_mode", self._settings))
        self._emoji_mode_cb.setToolTip(tr("emoji_mode_tooltip", self._settings))
        self._text_optimization_group.setTitle(tr("group_text_optimization", self._settings))
        self._text_optimization_cb.setText(tr("text_optimization_enabled", self._settings))
        self._text_optimization_cb.setToolTip(tr("text_optimization_enabled_tooltip", self._settings))
        self._text_formatting_cb.setText(tr("text_optimization_formatting", self._settings))
        self._text_cleanup_cb.setText(tr("text_optimization_cleanup", self._settings))
        self._text_redact_cb.setText(tr("text_optimization_redact", self._settings))
        self._text_translation_cb.setText(tr("text_translation_enabled", self._settings))
        self._text_translation_target_label.setText(tr("text_translation_target", self._settings))
        self._text_optimization_note.setText(tr("text_optimization_note", self._settings))
        for i in range(self._text_translation_target_combo.count()):
            language = self._text_translation_target_combo.itemData(i)
            self._text_translation_target_combo.setItemText(
                i, localized_spoken_language_name(language, self._settings)
            )
        self._version_label.setText(tr("version_label", self._settings, version=app_version()))
        self._save_btn.setText(tr("save", self._settings))
        self._cancel_btn.setText(tr("cancel", self._settings))
        self._rebuild_language_combos()
        self._refresh_mics()

    def _rebuild_language_combos(self) -> None:
        current_language = self._settings.language
        current_ui_language = self._settings.ui_language

        self._lang_combo.clear()
        for code in LANGUAGE_CYCLE:
            self._lang_combo.addItem(localized_spoken_language_name(code, self._settings), code)
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == current_language:
                self._lang_combo.setCurrentIndex(i)
                break

        self._ui_lang_combo.clear()
        for code in UI_LANGUAGE_CYCLE:
            self._ui_lang_combo.addItem(UI_LANGUAGES[code], code)
        for i in range(self._ui_lang_combo.count()):
            if self._ui_lang_combo.itemData(i) == current_ui_language:
                self._ui_lang_combo.setCurrentIndex(i)
                break

    def _refresh_mics(self) -> None:
        current_index = self._settings.microphone_index
        current_name = self._settings.microphone_name
        self._mic_combo.clear()
        self._mic_combo.addItem(tr("microphone_default", self._settings), None)
        for mic in list_microphones():
            self._mic_combo.addItem(mic["name"], mic["index"])
        # Restore selection by index first, then by name as fallback.
        for i in range(self._mic_combo.count()):
            if self._mic_combo.itemData(i) == current_index:
                self._mic_combo.setCurrentIndex(i)
                return
        if current_name:
            for i in range(self._mic_combo.count()):
                if self._mic_combo.itemText(i) == current_name:
                    self._mic_combo.setCurrentIndex(i)
                    return

    def _populate(self) -> None:
        self._hk_record.setText(self._settings.hotkey_record)
        self._hk_lang.setText(self._settings.hotkey_language)

        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == self._settings.language:
                self._lang_combo.setCurrentIndex(i)

        for i in range(self._ui_lang_combo.count()):
            if self._ui_lang_combo.itemData(i) == self._settings.ui_language:
                self._ui_lang_combo.setCurrentIndex(i)

        for i in range(self._live_model_combo.count()):
            if self._live_model_combo.itemText(i) == self._settings.live_whisper_model:
                self._live_model_combo.setCurrentIndex(i)

        for i in range(self._final_model_combo.count()):
            if self._final_model_combo.itemText(i) == self._settings.final_whisper_model:
                self._final_model_combo.setCurrentIndex(i)

        self._refresh_compute_devices()

        self._auto_insert_cb.setChecked(self._settings.auto_insert)
        self._keep_model_loaded_cb.setChecked(self._settings.keep_model_loaded)
        self._live_transcription_cb.setChecked(self._settings.live_transcription_enabled)
        self._emoji_mode_cb.setChecked(self._settings.emoji_mode_enabled)
        self._text_optimization_cb.setChecked(self._settings.text_optimization_enabled)
        self._text_formatting_cb.setChecked(self._settings.text_optimization_formatting_enabled)
        self._text_cleanup_cb.setChecked(self._settings.text_optimization_cleanup_enabled)
        self._text_redact_cb.setChecked(self._settings.text_optimization_redact_enabled)
        self._text_translation_cb.setChecked(self._settings.text_translation_enabled)
        for i in range(self._text_translation_target_combo.count()):
            if self._text_translation_target_combo.itemData(i) == self._settings.text_translation_target_language:
                self._text_translation_target_combo.setCurrentIndex(i)
                break
        self._update_text_optimization_controls(self._text_optimization_cb.isChecked())
        self._refresh_mics()

    def _update_text_optimization_controls(self, _checked: bool) -> None:
        enabled = self._text_optimization_cb.isChecked()
        self._text_formatting_cb.setEnabled(enabled)
        self._text_cleanup_cb.setEnabled(enabled)
        self._text_redact_cb.setEnabled(enabled)
        self._text_translation_cb.setEnabled(True)
        translation_enabled = self._text_translation_cb.isChecked()
        self._text_translation_target_label.setEnabled(translation_enabled)
        self._text_translation_target_combo.setEnabled(translation_enabled)
        self._text_optimization_note.setEnabled(enabled)

    def _refresh_compute_devices(self) -> None:
        """Populate CPU, automatic, and all Vulkan devices found at runtime."""
        selected = self._settings.compute_device
        self._compute_combo.clear()
        self._compute_combo.addItem(tr("compute_auto", self._settings), COMPUTE_DEVICE_AUTO)
        self._compute_combo.addItem(tr("compute_cpu", self._settings), COMPUTE_DEVICE_CPU)
        available_ids: set[str] = set()
        for index, name in list_vulkan_devices():
            device_id = f"gpu:{index}"
            available_ids.add(device_id)
            self._compute_combo.addItem(
                tr("compute_gpu", self._settings, index=index, name=name),
                device_id,
            )

        # Preserve a configured GPU choice even when it is temporarily
        # unavailable (for example when an external GPU is disconnected).
        if selected.startswith("gpu:") and selected not in available_ids:
            index = selected.removeprefix("gpu:")
            self._compute_combo.addItem(
                tr("compute_gpu_unavailable", self._settings, index=index),
                selected,
            )

        for i in range(self._compute_combo.count()):
            if self._compute_combo.itemData(i) == selected:
                self._compute_combo.setCurrentIndex(i)
                break

    def _save(self) -> None:
        if not self._change_rules_path():
            return
        for model_id in (self._final_model_combo.currentText(), self._text_model_combo.currentData()):
            selected = self._model_manager.manager.catalog.get("large-v3" if model_id == "large" else model_id)
            activated = self._model_manager.manager.installed_spec(selected.id) if selected else None
            if selected is None or not (selected.compatible or (activated and activated.compatible)):
                QMessageBox.warning(self, tr("models", self._settings), tr("incompatible", self._settings))
                return
        try:
            self._settings.correction_rules = self._table_rules()
        except ValueError as exc:
            QMessageBox.warning(self, tr("correction_rules", self._settings), tr(str(exc), self._settings))
            return
        self._settings.correction_rules_enabled = self._rules_enabled.isChecked()
        self._settings.hotkey_record = self._hk_record.text().strip()
        self._settings.hotkey_language = self._hk_lang.text().strip()
        self._settings.language = self._lang_combo.currentData()
        self._settings.ui_language = self._ui_lang_combo.currentData()
        self._settings.microphone_index = self._mic_combo.currentData()
        self._settings.microphone_name = None if self._mic_combo.currentIndex() == 0 else self._mic_combo.currentText()
        self._settings.live_whisper_model = self._live_model_combo.currentText()
        self._settings.final_whisper_model = self._final_model_combo.currentText()
        self._settings.text_model = self._text_model_combo.currentData()
        self._settings.compute_device = self._compute_combo.currentData()
        self._settings.keep_model_loaded = self._keep_model_loaded_cb.isChecked()
        self._settings.auto_insert = self._auto_insert_cb.isChecked()
        self._settings.live_transcription_enabled = self._live_transcription_cb.isChecked()
        self._settings.emoji_mode_enabled = self._emoji_mode_cb.isChecked()
        self._settings.text_optimization_enabled = self._text_optimization_cb.isChecked()
        self._settings.text_optimization_formatting_enabled = self._text_formatting_cb.isChecked()
        self._settings.text_optimization_cleanup_enabled = self._text_cleanup_cb.isChecked()
        self._settings.text_optimization_redact_enabled = self._text_redact_cb.isChecked()
        self._settings.text_translation_enabled = self._text_translation_cb.isChecked()
        self._settings.text_translation_target_language = self._text_translation_target_combo.currentData()
        try:
            self._settings.correction_rules_path = self._rules_path
            try:
                self._settings.save_rules(expected_revision=self._rules_revision)
            except RulesConflict:
                conflicted_revision = RuleStore(self._rules_path).revision()
                if QMessageBox.question(self, tr("correction_rules", self._settings), tr("rules_conflict", self._settings),
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
                # Recheck immediately before replacement; do not suppress a
                # second change made while the confirmation was displayed.
                self._settings.save_rules(expected_revision=conflicted_revision)
            self._rules_revision = self._settings._rules_revision
            self._settings.save()
        except (OSError, RulesFileError) as exc:
            detail = self._rules_error_text(exc) if isinstance(exc, RulesFileError) else str(exc)
            QMessageBox.warning(self, tr("settings_title", self._settings), tr("save_failed", self._settings) + "\n" + detail)
            return
        self._original_settings.__dict__.update(self._settings.snapshot().__dict__)
        self._settings = self._original_settings
        self.accept()
        QTimer.singleShot(0, lambda: self.settings_saved.emit(self._settings))
