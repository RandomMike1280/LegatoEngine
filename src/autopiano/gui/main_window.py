"""The main window: a permission banner, then the Convert, Play and Edit tabs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..format.apno import EXTENSION
from ..player.permissions import can_send_keys, open_accessibility_settings, request_key_access
from . import settings
from .convert_panel import ConvertPanel
from .edit_panel import EditPanel
from .player_panel import PlayerPanel
from .preview import PreviewPlayer, SpaceListens
from .widgets import dropped, dropped_songs


class PermissionBanner(QFrame):
    """Shown until macOS lets AutoPiano press keys in other apps."""

    def __init__(self, on_granted, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_granted = on_granted
        self.setObjectName("banner")
        self.setStyleSheet(
            "#banner { background: rgba(240, 140, 58, 0.16); border: 1px solid rgba(240, 140, 58, 0.5); border-radius: 8px; }"
        )
        text = QLabel(
            "<b>AutoPiano needs the Accessibility permission</b> to press keys in Roblox and to hear its hotkeys. "
            "Converting and Test mode work without it."
        )
        text.setWordWrap(True)
        allow = QPushButton("Allow…")
        open_settings = QPushButton("Open Settings")
        layout = QHBoxLayout(self)
        layout.addWidget(text, 1)
        layout.addWidget(allow)
        layout.addWidget(open_settings)
        allow.clicked.connect(request_key_access)
        open_settings.clicked.connect(open_accessibility_settings)
        self._timer = QTimer(self, interval=2000)
        self._timer.timeout.connect(self.check)
        self.check()

    def check(self) -> None:
        granted = can_send_keys()
        self.setVisible(not granted)
        if granted:
            self._timer.stop()
            self._on_granted()
        elif not self._timer.isActive():
            self._timer.start()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoPiano")
        self.setAcceptDrops(True)
        self.preview = PreviewPlayer(self)
        self.preview.set_sustain(settings.load("listen/sustain", False))
        self.preview.sustain_changed.connect(lambda on: settings.save("listen/sustain", on))
        self.preview.failed.connect(lambda message: QMessageBox.warning(self, "Couldn't play the preview", message))
        self.convert_panel = ConvertPanel(self.preview)
        self.player_panel = PlayerPanel(self.preview)
        self.edit_panel = EditPanel(self.preview)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.convert_panel, "Convert")
        self.tabs.addTab(self.player_panel, "Play")
        self.tabs.addTab(self.edit_panel, "Edit")

        central = QWidget()
        self.banner = PermissionBanner(self.player_panel.start_hotkeys, central)  # parented first, or it opens as a window
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.convert_panel.saved.connect(self._saved)
        self.convert_panel.queue.open_requested.connect(self._saved)
        self.edit_panel.saved.connect(self._saved)
        self.player_panel.edit_requested.connect(self._edit)
        QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self).activated.connect(self._find)
        SpaceListens(self, self.preview, lambda: getattr(self.tabs.currentWidget(), "listen", None))
        self.tabs.setCurrentIndex(settings.load("window/tab", 0))
        self.tabs.currentChanged.connect(lambda i: settings.save("window/tab", i))
        geometry = settings.load("window/geometry", None)
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        else:
            self.resize(1180, 760)
        if not self.player_panel.hotkeys.active:
            self.player_panel.start_hotkeys()

    def _saved(self, path: str) -> None:
        self.player_panel.refresh(select=path)
        self.tabs.setCurrentWidget(self.player_panel)

    def _find(self) -> None:
        """⌘F: search the library."""
        self.tabs.setCurrentWidget(self.player_panel)
        self.player_panel.focus_search()

    def _edit(self, path: str) -> None:
        self.edit_panel.load(path)
        self.tabs.setCurrentWidget(self.edit_panel)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def open_path(self, path: str) -> None:
        """Opens a script in the Play tab, or starts converting a song."""
        if Path(path).suffix.lower() == EXTENSION:
            self.player_panel.open_file(path)
            self.tabs.setCurrentWidget(self.player_panel)
        else:
            self.convert_panel.set_file(path)
            self.tabs.setCurrentWidget(self.convert_panel)

    def dropEvent(self, event) -> None:
        songs = dropped_songs(event.mimeData())
        if len(songs) > 1:
            self.convert_panel.queue_songs(songs)
            self.tabs.setCurrentWidget(self.convert_panel)
            return
        path, link = dropped(event.mimeData())
        if path:
            self.open_path(path)
        elif link:
            self.convert_panel.set_link(link)
            self.tabs.setCurrentWidget(self.convert_panel)

    def closeEvent(self, event) -> None:
        self.preview.stop()
        self.player_panel.shutdown()
        self.convert_panel.shutdown()
        settings.save("window/geometry", self.saveGeometry())
        super().closeEvent(event)
