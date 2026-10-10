"""Asynchronous catalogue checks and cancellable, verified model downloads."""
import threading
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QPushButton, QMessageBox, QProgressDialog
from core.models import ModelManager, Cancelled, CatalogNotPublished
from config.localization import tr


class ModelManagerWidget(QWidget):
    changed = pyqtSignal()
    finished = pyqtSignal(object)
    progress = pyqtSignal(int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.manager = ModelManager()
        self._thread = None
        self._cancel = threading.Event()
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("models", settings), tr("version", settings), "MiB", tr("status", settings)])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.check = QPushButton(tr("check_updates", settings))
        self.download = QPushButton(tr("download", settings))
        self.check.clicked.connect(lambda: self._run(self.manager.refresh))
        self.download.clicked.connect(self._download)
        row.addWidget(self.check)
        row.addWidget(self.download)
        layout.addLayout(row)
        self.finished.connect(self._finished)
        self.progress.connect(self._progress)
        self._dialog = None
        self.refresh()

    def refresh(self):
        models = list(self.manager.catalog.values())
        self.table.setRowCount(len(models))
        for row, model in enumerate(models):
            path = self.manager.path(model)
            receipt = path.with_suffix(path.suffix + ".receipt.json")
            activated = self.manager.installed_spec(model.id)
            state = "incompatible" if not model.compatible else "installed" if self.manager.installed(model) else "update_available" if activated or receipt.exists() else "verification_required" if path.exists() else "available"
            for column, text in enumerate([model.name, model.revision[:12], f"{model.size / 1024**2:.0f}", tr(state, self.settings)]):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, model.id)
                item.setToolTip(f"{model.runtime} · WinWhisperPlus ≥ {model.minimum_app_version}\n{model.sha256}"
                               + (f"\n{tr('installed', self.settings)}: {activated.revision[:12]}" if activated else ""))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.changed.emit()

    def _download(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item is None:
            return
        model_id = item.data(Qt.ItemDataRole.UserRole)
        self._run(lambda: self.manager.ensure(model_id, self._cancel,
                                             lambda current, total: self.progress.emit(int(current / total * 100)),
                                             prefer_installed=False))

    def _run(self, action):
        if self._thread and self._thread.is_alive():
            return
        self._cancel.clear()
        self.check.setEnabled(False)
        self.download.setEnabled(False)
        self._dialog = QProgressDialog(tr("processing", self.settings), tr("cancel", self.settings), 0, 100, self)
        self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._dialog.setAutoClose(False)
        self._dialog.canceled.connect(self._cancel.set)
        self._dialog.setValue(0)
        self._dialog.show()

        def worker():
            try:
                action()
                error = None
            except Exception as exc:
                error = exc
            self.finished.emit(error)
        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def _progress(self, percent):
        if self._dialog:
            self._dialog.setValue(percent)

    def _finished(self, error):
        if self._dialog:
            self._dialog.close()
            self._dialog = None
        self.check.setEnabled(True)
        self.download.setEnabled(True)
        if isinstance(error, CatalogNotPublished):
            QMessageBox.information(self, tr("models", self.settings), tr("catalog_not_published", self.settings))
        elif error and not isinstance(error, Cancelled):
            QMessageBox.warning(self, tr("models", self.settings), str(error))
        self.refresh()

    def stop(self):
        self._cancel.set()
