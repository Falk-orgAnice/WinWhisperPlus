"""
System tray icon for MyWhisper.

The tray icon provides quick access to:
 - Start/stop recording
 - Open settings
 - Quit the application
It also shows the current status via tooltip and optional icon badge.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

from config.localization import tr
from utils.resources import resource_path


def _colorize_pixmap(pixmap: QPixmap, target_color: str) -> QPixmap:
    """Replace black pixels in pixmap with target color, preserving alpha."""
    if pixmap.isNull():
        return pixmap
    
    # Create a pixmap filled with target color
    colored = QPixmap(pixmap.size())
    colored.fill(QColor("transparent"))
    
    # Paint the target color using the source as alpha mask
    painter = QPainter(colored)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(colored.rect(), QColor(target_color))
    painter.end()
    
    return colored


def _make_icon(color: str, label: str = "") -> QIcon:
    """Generate a microphone icon SVG with status badge in specified color."""

    size = 32
    asset_path = resource_path("assets/icon.svg")
    
    # Load SVG and render at size
    pix = QPixmap(size, size)
    pix.fill(QColor("transparent"))
    svg = QPixmap(str(asset_path))
    
    if not svg.isNull():
        svg_scaled = svg.scaledToWidth(36, Qt.TransformationMode.SmoothTransformation)
        # Colorize the SVG with the target color
        svg_colored = _colorize_pixmap(svg_scaled, color)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Center SVG on pixmap
        offset_x = (size - svg_colored.width()) // 2
        offset_y = (size - svg_colored.height()) // 2
        painter.drawPixmap(offset_x, offset_y, svg_colored)
    else:
        # Fallback: draw simple microphone if SVG not found
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(QColor(color))
        painter.drawRoundedRect(11, 4, 10, 14, 3, 3)
        painter.drawRect(14, 16, 4, 8)
    
    # Draw status badge in bottom-right corner
    badge_size = 10
    badge_x = size - badge_size - 1
    badge_y = size - badge_size - 1
    painter = QPainter(pix)
    painter.setBrush(QColor(color))
    painter.setPen(QColor("white"))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawEllipse(badge_x, badge_y, badge_size, badge_size)
    
    # Optional label in badge
    if label:
        font = QFont("Arial", 6, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(badge_x, badge_y, badge_size, badge_size, 0x0084, label)
    
    painter.end()
    return QIcon(pix)


# Status colours - lazy initialization to avoid QPixmap before QApplication
_ICONS = {}

def _init_icons() -> None:
    """Initialize icons after QApplication is created."""
    global _ICONS
    if not _ICONS:
        _ICONS = {
            "initializing": _make_icon("#FF9800", "…"),   # orange (initializing)
            "ready":       _make_icon("#4CAF50", "M"),   # green
            "recording":   _make_icon("#F44336", "●"),   # red
            "processing":  _make_icon("#FF9800", "…"),   # orange
            "inserted":    _make_icon("#2196F3", "✓"),   # blue
        }


class TrayIcon(QObject):
    """Wraps QSystemTrayIcon with application-specific behaviour."""

    toggle_recording_requested = pyqtSignal()
    open_settings_requested = pyqtSignal()
    open_history_requested = pyqtSignal()
    open_statistics_requested = pyqtSignal()
    open_log_requested = pyqtSignal()
    retry_failed_transcription_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: QObject | None = None, settings=None) -> None:
        super().__init__(parent)
        self._settings = settings
        _init_icons()  # Initialize icons after QApplication is created
        self._tray = QSystemTrayIcon(parent=None)
        self._tray.setIcon(_ICONS["initializing"])
        self._record_action = None
        self._history_action = None
        self._statistics_action = None
        self._retry_failed_transcription_action = None
        self._retry_failed_transcription_available = False
        self._log_action = None
        self._settings_action = None
        self._quit_action = None
        self._build_menu()
        self.retranslate_ui("initializing")
        self._tray.activated.connect(self._on_activated)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def set_status(self, status: str) -> None:
        """Update icon and tooltip to reflect *status*."""
        icon = _ICONS.get(status, _ICONS["ready"])
        label = tr(status, self._settings)
        self._tray.setIcon(icon)
        self._tray.setToolTip(f'{tr("app_name", self._settings)} - {label}')
        self._record_action.setText(
            tr("record_stop", self._settings) if status == "recording" else tr("record_start", self._settings)
        )

    def set_retry_failed_transcription_available(self, available: bool) -> None:
        """Enable retry only while a recoverable recording exists."""
        self._retry_failed_transcription_available = available
        if self._retry_failed_transcription_action is not None:
            self._retry_failed_transcription_action.setEnabled(available)

    def retranslate_ui(self, status: str = "ready") -> None:
        """Refresh all translated tray strings."""
        if self._history_action is not None:
            self._history_action.setText(tr("history", self._settings))
        if self._statistics_action is not None:
            self._statistics_action.setText(tr("statistics", self._settings))
        if self._retry_failed_transcription_action is not None:
            self._retry_failed_transcription_action.setText(tr("retry_failed_transcription", self._settings))
        if self._log_action is not None:
            self._log_action.setText(tr("open_log", self._settings))
        if self._settings_action is not None:
            self._settings_action.setText(tr("settings", self._settings))
        if self._quit_action is not None:
            self._quit_action.setText(tr("quit", self._settings))
        self.set_status(status)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu()

        self._record_action = menu.addAction(tr("record_start", self._settings))
        self._record_action.triggered.connect(self.toggle_recording_requested)

        menu.addSeparator()

        self._history_action = menu.addAction(tr("history", self._settings))
        self._history_action.triggered.connect(self.open_history_requested)

        self._statistics_action = menu.addAction(tr("statistics", self._settings))
        self._statistics_action.triggered.connect(self.open_statistics_requested)

        self._retry_failed_transcription_action = menu.addAction(tr("retry_failed_transcription", self._settings))
        self._retry_failed_transcription_action.triggered.connect(self.retry_failed_transcription_requested)
        self._retry_failed_transcription_action.setEnabled(self._retry_failed_transcription_available)

        self._log_action = menu.addAction(tr("open_log", self._settings))
        self._log_action.triggered.connect(self.open_log_requested)

        self._settings_action = menu.addAction(tr("settings", self._settings))
        self._settings_action.triggered.connect(self.open_settings_requested)

        menu.addSeparator()

        self._quit_action = menu.addAction(tr("quit", self._settings))
        self._quit_action.triggered.connect(self.quit_requested)

        self._tray.setContextMenu(menu)

    def _on_activated(self, reason) -> None:
        try:
            # In PyQt6, we need to check the reason value directly
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick or reason == 2:
                self.toggle_recording_requested.emit()
        except (TypeError, AttributeError):
            # Fallback for different PyQt versions
            if reason == 2:  # DoubleClick
                self.toggle_recording_requested.emit()
