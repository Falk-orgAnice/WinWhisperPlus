"""
Small always-visible status window that shows the current application state.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QMoveEvent, QContextMenuEvent, QIcon, QPixmap, QColor, QPainter, QFont
from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout, QMenu, QProgressBar

from config.localization import tr
from utils.resources import resource_path

_STATUS_COLORS = {
    "initializing": "#FF9800",
    "ready":      "#4CAF50",
    "recording":  "#F44336",
    "processing": "#FF9800",
    "inserted":   "#2196F3",
}

_PRIMARY_FONT_SIZE = 12
_PRIMARY_MESSAGE_FONT_SIZE = 11
_SECONDARY_FONT_SIZE = 10


def _format_hotkey(hotkey: str) -> str:
    """Convert hotkey format from 'alt+shift+r' to 'Alt+Shift+R'."""
    parts = hotkey.split("+")
    formatted = [part.capitalize() for part in parts]
    return "+".join(formatted)


class StatusWindow(QWidget):
    """Compact floating status widget."""

    toggle_recording_requested = pyqtSignal()
    open_settings_requested = pyqtSignal()
    open_history_requested = pyqtSignal()
    open_statistics_requested = pyqtSignal()
    open_log_requested = pyqtSignal()
    retry_failed_transcription_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, hotkey_record: str = "", settings=None) -> None:
        super().__init__()
        self._settings = settings
        self.setWindowTitle(tr("app_name", self._settings))
        self._base_status = "initializing"
        self.setWindowIcon(self._make_app_icon(self._base_status))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setFixedSize(130, 60)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)

        # Icon and label on the same row (top)
        from PyQt6.QtWidgets import QHBoxLayout
        icon_and_label_layout = QHBoxLayout()
        icon_and_label_layout.setContentsMargins(0, 0, 0, 0)
        icon_and_label_layout.setSpacing(3)
        icon_and_label_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedSize(24, 24)
        icon_and_label_layout.addWidget(self._icon_label)

        self._label = QLabel(tr("initializing", self._settings))
        self._label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._label.setWordWrap(True)
        self._label.setFixedSize(82, 34)
        self._label.setStyleSheet(f"font-size: {_PRIMARY_FONT_SIZE}px; font-weight: bold;")
        icon_and_label_layout.addWidget(self._label)
        
        self._layout.addLayout(icon_and_label_layout)

        # Second row (normal state): hotkey information.
        self._hotkey_label = QLabel()
        self._hotkey_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hotkey_label.setFixedHeight(12)
        self._hotkey_label.setStyleSheet(f"font-size: {_SECONDARY_FONT_SIZE}px; color: #666;")
        self._layout.addWidget(self._hotkey_label)

        # Second row (loading state): progress indicator.
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(10)
        self._progress_bar.hide()
        self._layout.addWidget(self._progress_bar)

        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(self._clear_message)
        self._base_status = "initializing"
        self._loading_active = False
        self._loading_message = tr("loading_models_generic", self._settings)
        self._hotkey_record = _format_hotkey(hotkey_record) if hotkey_record else ""
        self._record_action = None  # Will be created when context menu is first built
        self._retry_failed_transcription_available = False
        self._refresh_primary_line()
        self._update_hotkey_display()
        self._update_second_line_visibility()
        self._update_icon_display(self._base_status)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        self._base_status = status
        if not self._msg_timer.isActive() and not self._loading_active:
            self._refresh_primary_line()
        # Update window and icon display with status color
        self.setWindowIcon(self._make_app_icon(status))
        self._update_icon_display(status)
        # Update context menu recording action text
        if self._record_action:
            self._record_action.setText(
                tr("record_stop", self._settings) if status == "recording" else tr("record_start", self._settings)
            )

    def set_hotkey(self, hotkey_record: str) -> None:
        """Update the displayed hotkey."""
        self._hotkey_record = _format_hotkey(hotkey_record) if hotkey_record else ""
        self._update_hotkey_display()

    def load_position(self) -> None:
        """Load and restore the window position from settings."""
        if self._settings and self._settings.window_position_x is not None and self._settings.window_position_y is not None:
            self.move(self._settings.window_position_x, self._settings.window_position_y)

    def show_message(self, message: str, duration_ms: int = 2500) -> None:
        """Show a temporary overlay message for *duration_ms* milliseconds."""
        self._label.setText(message)
        self._label.setStyleSheet(
            f"font-size: {_PRIMARY_MESSAGE_FONT_SIZE}px; font-weight: bold; color: #9C27B0;"
        )
        self._msg_timer.start(duration_ms)

    def set_loading(self, active: bool, message: str | None = None) -> None:
        """Show or hide loading mode with progress in line 2."""
        self._loading_active = active
        self._loading_message = message or tr("loading_models_generic", self._settings)
        icon_status = "processing" if active else self._base_status
        self.setWindowIcon(self._make_app_icon(icon_status))
        self._update_icon_display(icon_status)
        self._update_second_line_visibility()
        if not self._msg_timer.isActive():
            self._refresh_primary_line()

    def retranslate_ui(self) -> None:
        """Refresh all translated UI strings."""
        self.setWindowTitle(tr("app_name", self._settings))
        if not self._msg_timer.isActive():
            self._refresh_primary_line()
        self._update_hotkey_display()
        if self._record_action:
            self._record_action.setText(
                tr("record_stop", self._settings) if self._base_status == "recording" else tr("record_start", self._settings)
            )

    def set_retry_failed_transcription_available(self, available: bool) -> None:
        """Enable the recovery action only if a saved recording is available."""
        self._retry_failed_transcription_available = available

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_hotkey_display(self) -> None:
        """Update the hotkey display label."""
        if self._hotkey_record:
            self._hotkey_label.setText(self._hotkey_record)
        else:
            self._hotkey_label.setText("")

    def _update_second_line_visibility(self) -> None:
        """Only one element may be visible in the second line."""
        loading = self._loading_active
        self._hotkey_label.setVisible(not loading)
        self._progress_bar.setVisible(loading)
        if loading:
            self._progress_bar.setRange(0, 0)
            self._progress_bar.setTextVisible(False)

    def _refresh_primary_line(self) -> None:
        """Apply current line 1 text based on message/loading/status priority."""
        if self._loading_active:
            self._label.setText(self._loading_message)
            self._label.setStyleSheet(f"font-size: {_PRIMARY_FONT_SIZE}px; font-weight: bold; color: #FF9800;")
            return
        self._apply_status(self._base_status)

    def _apply_status(self, status: str) -> None:
        text = tr(status, self._settings)
        color = _STATUS_COLORS.get(status, "#000000")
        self._label.setText(text)
        self._label.setStyleSheet(
            f"font-size: {_PRIMARY_FONT_SIZE}px; font-weight: bold; color: {color};"
        )

    def _clear_message(self) -> None:
        self._refresh_primary_line()

    def _update_icon_display(self, status: str) -> None:
        """Update the icon display in the window."""
        icon = self._make_app_icon(status)
        self._icon_label.setPixmap(icon.pixmap(24, 24))

    def _make_app_icon(self, status: str = "ready") -> QIcon:
        """Create colored microphone icon for window based on status."""
        from gui.tray_icon import _colorize_pixmap

        asset_path = resource_path("assets/icon.svg")
        color = _STATUS_COLORS.get(status, "#4CAF50")
        
        # Load SVG at larger size for window icon
        icon = QIcon()
        svg = QPixmap(str(asset_path))
        
        if not svg.isNull():
            # Add multiple sizes for better display in different contexts
            for size in [16, 32, 64, 128]:
                svg_scaled = svg.scaledToWidth(size, Qt.TransformationMode.SmoothTransformation)
                svg_colored = _colorize_pixmap(svg_scaled, color)
                icon.addPixmap(svg_colored)
            return icon
        
        # Fallback: load SVG directly as QIcon
        return QIcon(str(asset_path))

    def moveEvent(self, event: QMoveEvent) -> None:
        """Save window position when it moves."""
        super().moveEvent(event)
        if self._settings:
            self._settings.window_position_x = self.x()
            self._settings.window_position_y = self.y()
            self._settings.save()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Display context menu on right-click."""
        menu = self._build_context_menu()
        menu.exec(event.globalPos())

    def _build_context_menu(self) -> QMenu:
        """Build context menu with same options as TrayIcon."""
        menu = QMenu(self)
        
        # Recording action
        self._record_action = menu.addAction(tr("record_start", self._settings))
        self._record_action.triggered.connect(self.toggle_recording_requested.emit)
        
        # Separator
        menu.addSeparator()
        
        # History action
        history_action = menu.addAction(tr("history", self._settings))
        history_action.triggered.connect(self.open_history_requested.emit)

        # Statistics action
        statistics_action = menu.addAction(tr("statistics", self._settings))
        statistics_action.triggered.connect(self.open_statistics_requested.emit)

        retry_action = menu.addAction(tr("retry_failed_transcription", self._settings))
        retry_action.triggered.connect(self.retry_failed_transcription_requested.emit)
        retry_action.setEnabled(self._retry_failed_transcription_available)

        log_action = menu.addAction(tr("open_log", self._settings))
        log_action.triggered.connect(self.open_log_requested.emit)
        
        # Settings action
        settings_action = menu.addAction(tr("settings", self._settings))
        settings_action.triggered.connect(self.open_settings_requested.emit)
        
        # Separator
        menu.addSeparator()
        
        # Quit action
        quit_action = menu.addAction(tr("quit", self._settings))
        quit_action.triggered.connect(self.quit_requested.emit)
        
        return menu
