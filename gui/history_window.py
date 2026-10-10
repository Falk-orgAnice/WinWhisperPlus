"""Session audio history, result versions and explicit exports/insertion."""
from pathlib import Path
import shutil
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QTimer
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                            QPushButton, QLabel, QComboBox, QTextEdit, QTabWidget,
                            QFileDialog, QMessageBox, QApplication)
from config.localization import tr


class HistoryWindow(QDialog):
    text_selected = pyqtSignal(str)
    open_audio_requested = pyqtSignal()
    recognize_requested = pyqtSignal(object)
    retry_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._settings = settings
        self._jobs = []
        self._playing_job = None
        self.resize(950, 650)
        root = QVBoxLayout(self)
        self._title = QLabel()
        root.addWidget(self._title)
        self._list = QListWidget()
        root.addWidget(self._list)
        self._buttons = {}
        audio_row = QHBoxLayout()
        retry_row = QHBoxLayout()
        text_row = QHBoxLayout()
        actions = {"audio_open": lambda: self.open_audio_requested.emit(), "play": self._play,
                   "audio_export": self._export_audio, "recognize_again": lambda: self._emit_job(self.recognize_requested),
                   "retry_sections": lambda: self._emit_job(self.retry_requested), "cancel": self._cancel,
                   "delete": self._delete, "copy": self._copy, "text_export": self._export_text,
                   "insert": self._on_insert, "close": self.close}
        for key, action in actions.items():
            button = QPushButton()
            button.clicked.connect(action)
            self._buttons[key] = button
            row = text_row if key in {"copy", "text_export", "insert", "close"} else retry_row if key in {"retry_sections", "cancel", "delete"} else audio_row
            row.addWidget(button)
        root.addLayout(audio_row)
        root.addLayout(retry_row)
        self._versions = QComboBox()
        root.addWidget(self._versions)
        self._detail = QLabel()
        self._detail.setWordWrap(True)
        root.addWidget(self._detail)
        self._tabs = QTabWidget()
        self._original, self._result = QTextEdit(), QTextEdit()
        for editor in (self._original, self._result):
            editor.setReadOnly(True)
            self._tabs.addTab(editor, "")
        root.addWidget(self._tabs)
        self._tabs.setCurrentIndex(1)
        root.addLayout(text_row)
        self._insert_btn, self._close_btn = self._buttons["insert"], self._buttons["close"]
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._versions.currentIndexChanged.connect(self._show_version)
        self._tabs.currentChanged.connect(self._update_buttons)
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.errorOccurred.connect(self._on_playback_error)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_running)
        self._timer.start(500)
        self.retranslate_ui()

    def _error(self, message):
        QMessageBox.warning(self, tr("error", self._settings), str(message))

    def set_jobs(self, jobs):
        selected = self._selected_job()
        self._jobs = list(jobs)
        self._list.blockSignals(True)
        self._list.clear()
        for job in reversed(jobs):
            item = QListWidgetItem(self._job_label(job))
            item.setData(Qt.ItemDataRole.UserRole, job)
            self._list.addItem(item)
            if job is selected:
                self._list.setCurrentItem(item)
        if self._list.currentRow() < 0 and self._list.count():
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        self._on_selection_changed()

    def set_history(self, history):
        self._list.clear()
        for text in reversed(history):
            if text.strip():
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, text)
                self._list.addItem(item)

    def _job_label(self, job):
        status = job.versions[-1].status if job.versions else "recording"
        label = tr(status if status in {"recording", "complete", "cancelled", "processing", "translation_failed", "optimization_failed"} else "error", self._settings)
        return f"{job.created:%H:%M:%S} · {job.duration / 60:.1f} min · {label}" + (f" · {job.phase}" if job.running and job.phase else f" {job.progress:.0%}" if job.running else "")

    def _selected_job(self):
        item = self._list.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return value if value is not None and not isinstance(value, str) else None

    def refresh_job(self, job):
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is job:
                item.setText(self._job_label(job))
        if self._selected_job() is job:
            if self._versions.count() != len(job.versions):
                self._on_selection_changed()
            else:
                self._show_version()

    def _refresh_running(self):
        if self.isVisible():
            for job in self._jobs:
                if job.running:
                    self.refresh_job(job)

    def _on_selection_changed(self):
        job = self._selected_job()
        if job is not self._playing_job:
            self.stop_playback()
        self._versions.blockSignals(True)
        self._versions.clear()
        if job:
            for i, version in enumerate(job.versions):
                self._versions.addItem(f"{tr('version', self._settings)} {i + 1} · {version.model} · {version.language or 'auto'} → {version.target or '—'}", version)
            self._versions.setCurrentIndex(self._versions.count() - 1)
        self._versions.blockSignals(False)
        self._show_version()

    def _show_version(self):
        version = self._versions.currentData()
        if version:
            self._original.setPlainText(version.raw_text)
            self._result.setPlainText(version.text)
            self._detail.setText((tr("translation_failed", self._settings) if version.status == "translation_failed" else "") + "\n" + version.error + "\n" + "\n".join(version.warnings))
        else:
            item = self._list.currentItem()
            value = item.data(Qt.ItemDataRole.UserRole) if item else ""
            self._original.clear()
            self._result.setPlainText(value if isinstance(value, str) else "")
            self._detail.clear()
        self._update_buttons()

    def _text(self):
        return (self._original if self._tabs.currentIndex() == 0 else self._result).toPlainText()

    def _update_buttons(self):
        job = self._selected_job()
        for key in ("play", "audio_export", "recognize_again", "retry_sections", "cancel", "delete"):
            enabled = bool(job) and (job.running if key == "cancel" else not job.running)
            if key == "play" and self._playing_job is not None:
                enabled = True
            self._buttons[key].setEnabled(enabled)
        for key in ("copy", "text_export", "insert"):
            self._buttons[key].setEnabled(bool(self._text().strip()))

    def _play(self):
        if self._playing_job is not None:
            self.stop_playback()
            return
        job = self._selected_job()
        if job:
            self._player.setSource(QUrl.fromLocalFile(str(job.audio_path)))
            self._playing_job = job
            self._update_play_label()
            self._player.play()

    def _update_play_label(self):
        self._buttons["play"].setText(tr("stop_playback" if self._playing_job is not None else "play", self._settings))

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self._playing_job = None
        self._update_play_label()

    def _on_playback_error(self, *_):
        message = self._player.errorString()
        self.stop_playback()
        self._error(message)

    def _export_audio(self):
        job = self._selected_job()
        if not job:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("audio_export", self._settings), "dictation.wav", "WAV (*.wav)")
        if path:
            try:
                if Path(path).resolve() == job.audio_path.resolve():
                    raise ValueError("Choose a destination outside the session directory")
                shutil.copyfile(job.audio_path, path)
            except (OSError, ValueError) as exc:
                self._error(exc)

    def _export_text(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("text_export", self._settings), "transcript.txt", "Text (*.txt)")
        if path:
            try:
                Path(path).write_text(self._text(), encoding="utf-8")
            except OSError as exc:
                self._error(exc)

    def _copy(self):
        QApplication.clipboard().setText(self._text())

    def _emit_job(self, signal):
        job = self._selected_job()
        if job:
            signal.emit(job)

    def _cancel(self):
        job = self._selected_job()
        if job:
            job.cancel.set()

    def _delete(self):
        self.stop_playback()
        self._emit_job(self.delete_requested)

    def stop_playback(self):
        self._playing_job = None
        self._player.stop()
        self._player.setSource(QUrl())
        self._update_play_label()

    def _on_insert(self):
        text = self._text()
        if text.strip():
            self.close()
            QTimer.singleShot(150, lambda: self.text_selected.emit(text))

    def retranslate_ui(self):
        self.setWindowTitle(tr("history_title", self._settings))
        self._title.setText(tr("history_header", self._settings))
        for key, button in self._buttons.items():
            button.setText(tr(key, self._settings))
        self._update_play_label()
        self._tabs.setTabText(0, tr("original", self._settings))
        self._tabs.setTabText(1, tr("result", self._settings))
        self._update_buttons()

    def closeEvent(self, event):
        self.stop_playback()
        super().closeEvent(event)
