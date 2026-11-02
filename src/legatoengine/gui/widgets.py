"""Small widgets and helpers shared by the panels."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..format.apno import EXTENSION
from ..ingest.audio import AUDIO_EXTENSIONS
from ..ingest.convert import MIDI_EXTENSIONS
from ..models import Modifier, Role, Script
from .piano_roll import ROLE_COLORS

SONG_FILTER = "Songs ({})".format(" ".join(f"*{e}" for e in sorted(AUDIO_EXTENSIONS | MIDI_EXTENSIONS)))


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def script_summary(script: Script) -> str:
    notes = script.notes
    chords = script.chord_count
    shifted = sum(n.modifier is not Modifier.NONE for n in notes)
    from ..arrange.key import transposed_key_name

    meta = script.meta
    if meta.transpose:
        direction = "up" if meta.transpose > 0 else "down"
        key = f"{meta.key_name} → {transposed_key_name(meta.key_name, meta.transpose)} ({direction} {abs(meta.transpose)})"
    else:
        key = meta.key_name
    parts = [
        format_time(meta.duration),
        key,
        f"{len(notes)} notes in {chords} chords",
        f"{100 * shifted / max(1, len(notes)):.0f}% need Shift/Ctrl",
    ]
    return "  ·  ".join(p for p in parts if p)


def dropped(mime: QMimeData) -> tuple[str | None, str | None]:
    """What was dropped: (a local file, None), or else (None, a web link)."""
    urls = mime.urls()
    files = [u.toLocalFile() for u in urls if u.isLocalFile()]
    if files:
        return files[0], None
    links = [u.toString() for u in urls if u.scheme() in ("http", "https")]
    return None, links[0] if links else None


def dropped_songs(mime: QMimeData) -> list[str]:
    """Every song file and web link that was dropped, in order (scripts are left out)."""
    songs = []
    for url in mime.urls():
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() != EXTENSION:
            songs.append(url.toLocalFile())
        elif url.scheme() in ("http", "https"):
            songs.append(url.toString())
    return songs


def link_host(url: str) -> str:
    return (urlsplit(url).hostname or "the web").removeprefix("www.")


def move_to_trash(path: Path) -> str | None:
    """Moves a file to the Trash, so it can be put back. Returns an error message, or None."""
    from Foundation import NSURL, NSFileManager

    ok, _, error = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
        NSURL.fileURLWithPath_(str(path)), None, None
    )
    return None if ok else str(error.localizedDescription() if error is not None else "unknown error")


def secondary_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(placeholder-text);")
    return label


def title_label(text: str = "") -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 1.45)
    font.setBold(True)
    label.setFont(font)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class DropZone(QFrame):
    """Drop a song or a link here, or click to choose a song. Several at once go to the queue."""

    file_chosen = Signal(str)
    link_chosen = Signal(str)
    songs_chosen = Signal(list)  # more than one song file or link

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(96)
        self._hover = False
        layout = QVBoxLayout(self)
        self.label = QLabel("Drop a song or MIDI file here\nor click to choose one")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

    def show_file(self, path: str) -> None:
        self.label.setText(f"{Path(path).name}\n(drop or click to change)")

    def show_link(self, url: str) -> None:
        self.label.setText(f"A song from {link_host(url)}\n(Convert downloads it first)")

    def choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a song", str(Path.home() / "Music"), SONG_FILTER + ";;All files (*)")
        if path:
            self.file_chosen.emit(path)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.choose()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            self._hover = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def dropEvent(self, event) -> None:
        self._hover = False
        self.update()
        songs = dropped_songs(event.mimeData())
        if len(songs) > 1:
            self.songs_chosen.emit(songs)
            return
        path, link = dropped(event.mimeData())
        if path:
            self.file_chosen.emit(path)
        elif link:
            self.link_chosen.emit(link)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = self.palette().highlight().color() if self._hover else self.palette().mid().color()
        pen = p.pen()
        pen.setColor(color)
        pen.setWidthF(1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        if self._hover:
            fill = QColor(color)
            fill.setAlphaF(0.08)
            p.setBrush(fill)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        p.end()


class SearchField(QLineEdit):
    """A search box whose arrow keys move through the results while you keep typing. Esc clears it."""

    moved = Signal(int)  # +1 for the next result, -1 for the one before

    def __init__(self, placeholder: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.moved.emit(1 if event.key() == Qt.Key.Key_Down else -1)
        elif event.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
        else:
            super().keyPressEvent(event)


class Legend(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for role, name in ((Role.MELODY, "Melody"), (Role.BASS, "Bass"), (Role.HARMONY, "Chords")):
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {ROLE_COLORS[role].name()}; font-size: 14px;")
            layout.addWidget(dot)
            layout.addWidget(QLabel(name))
            layout.addSpacing(8)


