"""
Settings window – allows the user to configure hotkeys, language,
microphone and Whisper model size.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
)
from PyQt6.QtGui import QKeySequence

from config.localization import UI_LANGUAGES, localized_spoken_language_name, tr
from config.settings import LANGUAGE_CYCLE, UI_LANGUAGE_CYCLE, Settings
from core.recorder import list_microphones
from core.transcriber import COMPUTE_DEVICE_AUTO, COMPUTE_DEVICE_CPU, list_vulkan_devices
from utils.resources import app_version

if TYPE_CHECKING:
    pass

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]


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
        self._settings = settings
        self.setWindowTitle(tr("settings_title", self._settings))
        self.setMinimumWidth(420)
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # --- Hotkeys ---------------------------------------------------
        self._hk_group = QGroupBox()
        hk_form = QFormLayout(self._hk_group)
        self._hk_form = hk_form

        self._hk_record = HotkeyEdit()
        hk_form.addRow("", self._hk_record)

        self._hk_lang = HotkeyEdit()
        hk_form.addRow("", self._hk_lang)
        root.addWidget(self._hk_group)

        # --- Language --------------------------------------------------
        self._lang_group = QGroupBox()
        lang_layout = QHBoxLayout(self._lang_group)
        self._lang_combo = QComboBox()
        lang_layout.addWidget(self._lang_combo)
        root.addWidget(self._lang_group)

        self._ui_lang_group = QGroupBox()
        ui_lang_layout = QHBoxLayout(self._ui_lang_group)
        self._ui_lang_combo = QComboBox()
        ui_lang_layout.addWidget(self._ui_lang_combo)
        root.addWidget(self._ui_lang_group)

        # --- Microphone ------------------------------------------------
        self._mic_group = QGroupBox()
        mic_layout = QHBoxLayout(self._mic_group)
        self._mic_combo = QComboBox()
        mic_layout.addWidget(self._mic_combo)
        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setFixedWidth(30)
        self._refresh_btn.clicked.connect(self._refresh_mics)
        mic_layout.addWidget(self._refresh_btn)
        root.addWidget(self._mic_group)

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
        root.addWidget(self._model_group)

        # --- Compute device -------------------------------------------
        self._compute_group = QGroupBox()
        compute_layout = QHBoxLayout(self._compute_group)
        self._compute_label = QLabel()
        compute_layout.addWidget(self._compute_label)
        self._compute_combo = QComboBox()
        compute_layout.addWidget(self._compute_combo)
        root.addWidget(self._compute_group)
        self._keep_model_loaded_cb = QCheckBox()
        root.addWidget(self._keep_model_loaded_cb)

        # --- Auto insert -----------------------------------------------
        self._auto_insert_cb = QCheckBox()
        root.addWidget(self._auto_insert_cb)

        self._live_transcription_cb = QCheckBox()
        root.addWidget(self._live_transcription_cb)

        self._emoji_mode_cb = QCheckBox()
        root.addWidget(self._emoji_mode_cb)

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
        self._refresh_mics()

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
        self._settings.hotkey_record = self._hk_record.text().strip()
        self._settings.hotkey_language = self._hk_lang.text().strip()
        self._settings.language = self._lang_combo.currentData()
        self._settings.ui_language = self._ui_lang_combo.currentData()
        self._settings.microphone_index = self._mic_combo.currentData()
        self._settings.microphone_name = None if self._mic_combo.currentIndex() == 0 else self._mic_combo.currentText()
        self._settings.live_whisper_model = self._live_model_combo.currentText()
        self._settings.final_whisper_model = self._final_model_combo.currentText()
        self._settings.compute_device = self._compute_combo.currentData()
        self._settings.keep_model_loaded = self._keep_model_loaded_cb.isChecked()
        self._settings.auto_insert = self._auto_insert_cb.isChecked()
        self._settings.live_transcription_enabled = self._live_transcription_cb.isChecked()
        self._settings.emoji_mode_enabled = self._emoji_mode_cb.isChecked()
        self._settings.save()
        self.accept()
        QTimer.singleShot(0, lambda: self.settings_saved.emit(self._settings))
