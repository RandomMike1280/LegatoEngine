"""The Convert tab's queue: songs and links converted one after another, each saved to the library when done."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..arrange.pipeline import ArrangeError, ArrangeSettings, arrange
from ..format.apno import EXTENSION, write_script
from ..library import folders
from ..models import Song
from . import settings
from .widgets import format_time, secondary_label
from .workers import ConvertJob

WAITING, WORKING, SAVED, FAILED = "waiting", "working", "saved", "failed"
NEW_FOLDER = "\0new folder"  # the folder menu's last entry
FAILED_COLOR = QColor("#d9534f")


@dataclass(eq=False)
class QueueItem:
    source: str  # a song file or a link
    name: str  # what the list shows: the file name, or the link until its download names it
    state: str = WAITING
    detail: str = ""  # progress, where it was saved, or what went wrong
    downloaded: str = ""  # the link's song file, so trying again doesn't download it again
    saved: str = ""  # the script


def free_path(folder: Path, title: str) -> Path:
    """Where to save a script without replacing one: "Title.apno", else "Title (2).apno", and so on."""
    name = paths.safe_filename(title)
    path, n = folder / (name + EXTENSION), 2
    while path.exists():
        path, n = folder / f"{name} ({n}){EXTENSION}", n + 1
    return path


def _name(source: str) -> str:
    return Path(source).name if Path(source).is_absolute() else source.split("://", 1)[-1]


class QueueBox(QGroupBox):
    """Converts each queued song with the settings on the left of the Convert tab, then saves it.
    It waits while the tab converts a song of its own, and it remembers what's left between launches."""

    open_requested = Signal(str)  # a saved script was double-clicked

    def __init__(
        self,
        settings_for: Callable[[], tuple[str, ArrangeSettings]],
        busy: Callable[[], bool],
        parent: QWidget | None = None,
        job_type=ConvertJob,
    ):
        super().__init__("Queue", parent)
        self._settings_for = settings_for  # the song type and arrangement to use now
        self._busy = busy  # whether the tab is converting a song itself
        self._job_type = job_type
        self._items: list[QueueItem] = []
        self._rows: dict[QueueItem, QListWidgetItem] = {}
        self._job = None
        self._current: QueueItem | None = None
        self._arrangement: ArrangeSettings | None = None
        self._running = False

        self.status = QLabel()
        self.folder = QComboBox()
        self.folder.setToolTip("The library folder that converted songs are saved into")
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setAlternatingRowColors(True)  # like the Play tab's library
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setToolTip("Double-click a converted song to open it in the Play tab")
        self.start_button = QPushButton("Start")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear Converted")
        hint = secondary_label("Uses the Type and Arrangement settings on the left. Paste or drop more links to add them.")

        top = QHBoxLayout()
        top.addWidget(self.status, 1)
        top.addWidget(QLabel("Save into"))
        top.addWidget(self.folder)
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(self.remove_button)
        bottom.addWidget(self.clear_button)
        bottom.addWidget(self.start_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addLayout(bottom)

        self.start_button.clicked.connect(self.start_or_stop)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear_converted)
        self.list.itemSelectionChanged.connect(self._update)
        self.list.itemDoubleClicked.connect(self._open)
        self.folder.activated.connect(self._folder_chosen)
        for key in (QKeySequence(QKeySequence.StandardKey.Delete), QKeySequence(Qt.Key.Key_Backspace)):
            shortcut = QShortcut(key, self.list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)  # only while the list has focus
            shortcut.activated.connect(self.remove_selected)
        self._fill_folders()
        self._restore()
        self._update()

    # ---- what's queued

    def add(self, sources: list[str]) -> int:
        """Queues these songs and starts converting. Songs already in the queue are skipped; returns how many were new."""
        queued = {item.source for item in self._items if item.state != SAVED}
        new = [QueueItem(source, _name(source)) for source in dict.fromkeys(sources) if source not in queued]
        for item in new:
            self._append(item)
        if new:
            self._fill_folders(self.folder.currentData())  # picks up folders made since
            self._running = True
            self._save_queue()
            self._next()
        self._update()
        return len(new)

    @property
    def items(self) -> list[QueueItem]:
        return list(self._items)

    @property
    def running(self) -> bool:
        return self._running

    def start_or_stop(self) -> None:
        if self._running:
            self.stop()
            return
        if not any(item.state == WAITING for item in self._items):  # "Retry Failed"
            for item in self._items:
                if item.state == FAILED:
                    item.state, item.detail = WAITING, ""
                    self._show(item)
        self._running = True
        self._next()
        self._update()

    def stop(self) -> None:
        """Stops the song being converted; it starts over when the queue does."""
        self._running = False
        if self._current is not None:
            item = self._current
            self._cancel_job()
            item.state, item.detail = WAITING, "Stopped"
            self._show(item)
        self._update()

    def resume(self) -> None:
        """The tab finished converting its own song, so the queue may go on."""
        self._next()
        self._update()

    def remove_selected(self) -> None:
        self._remove([row.data(Qt.ItemDataRole.UserRole) for row in self.list.selectedItems()])

    def clear_converted(self) -> None:
        self._remove([item for item in self._items if item.state == SAVED])

    def shutdown(self) -> None:
        if self._current is not None:
            item = self._current
            self._cancel_job()
            item.state = WAITING
        self._save_queue()

    def _append(self, item: QueueItem) -> None:
        row = QListWidgetItem()
        row.setData(Qt.ItemDataRole.UserRole, item)
        self.list.addItem(row)
        self._rows[item] = row
        self._items.append(item)
        self._show(item)

    def _remove(self, chosen: list[QueueItem]) -> None:
        for item in chosen:
            if item is self._current:
                self._cancel_job()
            self.list.takeItem(self.list.row(self._rows.pop(item)))
            self._items.remove(item)
        self._save_queue()
        self._next()
        self._update()

    # ---- converting, one song at a time

    def _next(self) -> None:
        if not self._running or self._current is not None:
            return
        item = next((item for item in self._items if item.state == WAITING), None)
        if item is None:
            self._running = False
            return
        if self._busy():
            return  # resume() is called when the tab's own song is done
        kind, self._arrangement = self._settings_for()
        source = item.downloaded if item.downloaded and Path(item.downloaded).exists() else item.source
        self._current = item
        item.state, item.detail = WORKING, "Starting…"
        self._show(item)
        self._job = self._job_type(source, kind, self)
        self._job.progress.connect(self._on_progress)
        self._job.downloaded.connect(self._on_downloaded)
        self._job.finished.connect(self._on_converted)
        self._job.failed.connect(self._on_failed)
        self._job.start()

    def _cancel_job(self) -> None:
        if self._job is not None:
            self._job.cancel()
        self._job = self._current = None

    def _on_progress(self, label: str, fraction: float) -> None:
        if self._current is not None:
            self._current.detail = f"{label}… {round(fraction * 100)}%"
            self._show(self._current)

    def _on_downloaded(self, path: str, title: str) -> None:
        if self._current is not None:
            self._current.downloaded, self._current.name = path, title or self._current.name
            self._show(self._current)
            self._save_queue()

    def _on_converted(self, song: Song) -> None:
        item, arrangement = self._current, self._arrangement
        self._job = self._current = None
        if item is None:
            return
        folder = self._folder()
        try:
            script = arrange(song, arrangement)
            script.meta.title = song.title or Path(item.name).stem
            path = write_script(script, free_path(folder, script.meta.title))
        except ArrangeError as e:
            item.state, item.detail = FAILED, str(e)
        except OSError as e:
            item.state, item.detail = FAILED, f"The script couldn't be saved: {e.strerror}"
        else:
            where = "your library" if folder == paths.LIBRARY_DIR else folder.name
            item.state, item.saved = SAVED, str(path)
            item.detail = f"Saved to {where} as “{path.stem}” · {format_time(script.meta.duration)}"
        self._finished(item)

    def _on_failed(self, message: str, details: str) -> None:
        item = self._current
        self._job = self._current = None
        if item is not None:
            item.state, item.detail = FAILED, message
            self._finished(item)

    def _finished(self, item: QueueItem) -> None:
        self._show(item)
        self._save_queue()
        self._next()
        self._update()

    # ---- showing it

    def _show(self, item: QueueItem) -> None:
        row = self._rows[item]
        status = {WAITING: item.detail or "Waiting", WORKING: item.detail, SAVED: item.detail}.get(
            item.state, f"Failed: {item.detail}")
        row.setText(f"{item.name}\n{status}")
        row.setToolTip(item.source if item.state != FAILED else f"{item.source}\n\n{item.detail}")
        row.setData(Qt.ItemDataRole.ForegroundRole, FAILED_COLOR if item.state == FAILED else None)  # None: the theme's

    def _update(self) -> None:
        self.setVisible(bool(self._items))
        counts = Counter(item.state for item in self._items)
        waiting, saved, failed = counts[WAITING], counts[SAVED], counts[FAILED]
        if self._current is not None:
            parts = [f"Converting {saved + failed + 1} of {len(self._items)}"]
        elif self._running and waiting:
            parts = [f"{waiting} waiting until the song above is converted"]
        elif waiting:
            parts = [f"{waiting} waiting", f"{saved} converted"] if saved else [f"{waiting} waiting"]
        else:
            parts = [f"Done: {saved} converted"]
        if failed:
            parts.append(f"{failed} failed")
        self.status.setText(" · ".join(parts))
        self.start_button.setText("Stop" if self._running else "Start" if waiting or not failed else "Retry Failed")
        self.start_button.setEnabled(self._running or bool(waiting or failed))
        self.remove_button.setEnabled(bool(self.list.selectedItems()))
        self.clear_button.setEnabled(bool(saved))

    def _open(self, row: QListWidgetItem) -> None:
        item = row.data(Qt.ItemDataRole.UserRole)
        if item.saved and Path(item.saved).exists():
            self.open_requested.emit(item.saved)

    # ---- the folder to save into

    def _folder(self) -> Path:
        return paths.LIBRARY_DIR / (self.folder.currentData() or "")

    def _fill_folders(self, chosen: str | None = None) -> None:
        if chosen is None:
            chosen = settings.load("convert/queue_folder", "")
        root = paths.LIBRARY_DIR
        self.folder.blockSignals(True)
        self.folder.clear()
        self.folder.addItem("Library", "")
        for folder in folders(root):
            if folder != root and paths.DOWNLOADS_DIR not in (folder, *folder.parents):
                relative = folder.relative_to(root).as_posix()
                self.folder.addItem(relative, relative)
        if chosen and self.folder.findData(chosen) < 0:
            self.folder.addItem(chosen, chosen)  # made when the first script is saved into it
        self.folder.insertSeparator(self.folder.count())
        self.folder.addItem("New Folder…", NEW_FOLDER)
        self.folder.setCurrentIndex(max(0, self.folder.findData(chosen)))
        self.folder.blockSignals(False)

    def _folder_chosen(self, index: int) -> None:
        value = self.folder.itemData(index)
        if value == NEW_FOLDER:
            name, ok = QInputDialog.getText(self, "New Folder", "Name of the new folder in your library:")
            if ok and name.strip():
                settings.save("convert/queue_folder", paths.safe_filename(name))
            self._fill_folders()  # the new folder, or the one chosen before
            return
        settings.save("convert/queue_folder", value)

    # ---- remembering the queue between launches

    def _save_queue(self) -> None:
        left = [asdict(item) | ({"state": WAITING, "detail": ""} if item.state == WORKING else {})
                for item in self._items if item.state != SAVED]
        settings.save("convert/queue", json.dumps(left, ensure_ascii=False))

    def _restore(self) -> None:
        try:
            stored = json.loads(settings.load("convert/queue", "[]"))
        except ValueError:
            return
        names = {f.name for f in fields(QueueItem)}
        for data in stored if isinstance(stored, list) else []:
            try:
                self._append(QueueItem(**{key: value for key, value in data.items() if key in names}))
            except (AttributeError, TypeError):
                continue
