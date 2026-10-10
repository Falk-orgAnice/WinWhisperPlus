"""Source/model/translation choices shared by import and re-recognition."""
from PyQt6.QtWidgets import QDialog, QFormLayout, QComboBox, QDialogButtonBox
from config.localization import tr, localized_spoken_language_name
from config.settings import LANGUAGE_CYCLE
from core.transcriber import MODEL_FILENAMES
from core.models import ModelManager


class AudioOptionsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings.snapshot()
        self.setWindowTitle(tr("audio_open", settings))
        layout = QFormLayout(self)
        self._language = QComboBox()
        self._language.addItem(tr("auto_language", settings), "")
        for code in LANGUAGE_CYCLE:
            self._language.addItem(localized_spoken_language_name(code, settings), code)
        self._language.setCurrentIndex(max(0, self._language.findData(settings.language)))
        layout.addRow(tr("source_language", settings), self._language)
        self._model = QComboBox()
        manager = ModelManager()
        for model in ["large", *[m.id for m in manager.catalog.values() if m.kind == "speech"
                                and (m.compatible or (manager.installed_spec(m.id) and manager.installed_spec(m.id).compatible))]]:
            if model != "large-v3":
                self._model.addItem("large-v3" if model == "large" else model, model)
        self._model.setCurrentIndex(max(0, self._model.findData(settings.final_whisper_model)))
        layout.addRow(tr("final_model", settings), self._model)
        self._target = QComboBox()
        self._target.addItem(tr("no_translation", settings), None)
        for code in LANGUAGE_CYCLE:
            self._target.addItem(localized_spoken_language_name(code, settings), code)
        if settings.text_translation_enabled:
            self._target.setCurrentIndex(self._target.findData(settings.text_translation_target_language))
        layout.addRow(tr("text_translation_target", settings), self._target)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("start", settings))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel", settings))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def snapshot(self):
        result = self._settings.snapshot()
        result._data["language"] = self._language.currentData()
        result.final_whisper_model = self._model.currentData()
        result.text_translation_enabled = self._target.currentData() is not None
        if result.text_translation_enabled:
            result.text_translation_target_language = self._target.currentData()
        return result
