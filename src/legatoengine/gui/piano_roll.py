"""A scrolling piano-roll view of a script, colored by part, with a playhead and,
in the Edit tab, trim edges that can be dragged."""

from __future__ import annotations

import bisect

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QWidget

from ..layout import is_black
from ..models import Note, Role

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ROLE_COLORS = {
    Role.MELODY: QColor("#f08c3a"),
    Role.BASS: QColor("#4a90e2"),
    Role.HARMONY: QColor("#8e9aaf"),
}
MARGIN = 24  # pixels of empty time at the end
GUTTER = 30  # pixels for the octave labels, which stay put while the roll scrolls
TRIM_GRAB = 6  # pixels either side of a trim edge that pick it up
MIN_TRIM = 0.1  # seconds the trim edges stay apart


def _colors(widget: QWidget) -> dict[str, QColor]:
    dark = widget.palette().window().color().lightness() < 128
    return {
        "background": QColor("#1e1f24") if dark else QColor("#fbfbfc"),
        "black_row": QColor("#26272d") if dark else QColor("#f0f1f4"),
        "line": QColor("#34353c") if dark else QColor("#e1e3e8"),
        "label": QColor("#8a8d96") if dark else QColor("#777b85"),
    }


class PianoRoll(QWidget):
    seek_requested = Signal(float)
    range_changed = Signal()
    trim_changed = Signal(float, float)  # start, end: an edge is being dragged

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._notes: list[Note] = []
        self._starts: list[float] = []
        self._longest = 0.0
        self._beats: list[float] = []
        self._duration = 0.0
        self._low, self._high = 36, 96
        self._pps = 80.0  # pixels per second
        self._position: float | None = None
        self._trim: tuple[float, float] | None = None
        self._dragging: str | None = None  # the trim edge being dragged: "start" or "end"
        self._min_width = 400
        self.setMinimumHeight(160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ---- data

    def set_notes(self, notes: list[Note], duration: float, low: int, high: int, beats: list[float] = ()) -> None:
        self._notes = sorted(notes, key=lambda n: n.start)
        self._starts = [n.start for n in self._notes]
        self._longest = max((n.duration for n in self._notes), default=0.0)
        self._duration = duration
        self._low, self._high = low, high
        self._beats = list(beats)
        self._resize_to_content()
        self.update()
        self.range_changed.emit()

    @property
    def pitch_range(self) -> tuple[int, int]:
        return self._low, self._high

    def clear(self) -> None:
        self._trim = None
        self.set_notes([], 0.0, self._low, self._high)
        self._position = None

    def set_trim(self, start: float | None, end: float | None = None) -> None:
        """Shades what's before ``start`` and after ``end`` (default: the end), and lets
        their edges be dragged. ``None`` turns this off."""
        self._trim = None if start is None else (start, self._duration if end is None else end)
        self.setMouseTracking(self._trim is not None)
        self.update()

    def set_position(self, t: float | None) -> None:
        old = self._position
        self._position = t
        for x in (old, t):
            if x is not None:
                px = self.x_at(x)
                self.update(int(px) - 3, 0, 6, self.height())

    # ---- geometry

    def x_at(self, t: float) -> float:
        return t * self._pps

    def time_at(self, x: float) -> float:
        return max(0.0, x / self._pps)

    def set_viewport_width(self, width: int) -> None:
        self._min_width = width
        self._resize_to_content()

    def zoom(self, factor: float) -> None:
        self._pps = min(600.0, max(10.0, self._pps * factor))
        self._resize_to_content()
        self.update()

    @property
    def pixels_per_second(self) -> float:
        return self._pps

    def _resize_to_content(self) -> None:
        self.setFixedWidth(max(self._min_width, int(self.x_at(self._duration)) + MARGIN))

    # ---- drawing

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = event.rect()
        colors = _colors(self)
        p.fillRect(area, colors["background"])

        rows = self._high - self._low + 1
        row_h = self.height() / rows
        for pitch in range(self._low, self._high + 1):
            y = (self._high - pitch) * row_h
            if is_black(pitch):
                p.fillRect(QRectF(area.left(), y, area.width(), row_h), colors["black_row"])

        t0, t1 = self.time_at(area.left()), self.time_at(area.right() + 1)
        p.setPen(QPen(colors["line"], 1))
        for b in self._beats[bisect.bisect_left(self._beats, t0) : bisect.bisect_right(self._beats, t1)]:
            x = self.x_at(b)
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        for pitch in range(self._low, self._high + 1):
            if pitch % 12 == 0:  # a line under every C
                y = (self._high - pitch + 1) * row_h
                p.drawLine(QPointF(area.left(), y), QPointF(area.right() + 1, y))

        first = bisect.bisect_left(self._starts, t0 - self._longest)
        last = bisect.bisect_right(self._starts, t1)
        p.setPen(Qt.PenStyle.NoPen)
        for n in self._notes[first:last]:
            if n.end < t0:
                continue
            color = QColor(ROLE_COLORS.get(n.role, ROLE_COLORS[Role.HARMONY]))
            color.setAlphaF(0.55 + 0.45 * n.velocity / 127)
            p.setBrush(color)
            x = self.x_at(n.start)
            width = max(2.0, self.x_at(n.duration))
            y = (self._high - n.pitch) * row_h
            p.drawRoundedRect(QRectF(x, y + 0.5, width, max(2.0, row_h - 1)), 1.5, 1.5)

        if self._trim is not None:
            shade = QColor(colors["background"])
            shade.setAlphaF(0.75)
            edges = [self.x_at(t) for t in self._trim]
            p.fillRect(QRectF(0, 0, edges[0], self.height()), shade)
            p.fillRect(QRectF(edges[1], 0, self.width() - edges[1], self.height()), shade)
            edge_color = self.palette().highlight().color()
            p.setPen(QPen(edge_color, 2))
            for x in edges:
                p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(edge_color)
            for x in edges:  # a grip at the top of each edge
                p.drawRoundedRect(QRectF(x - 4, 0, 8, 16), 2, 2)

        if self._position is not None:
            x = self.x_at(self._position)
            p.setPen(QPen(QColor("#e5484d"), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        p.end()

    def _edge_at(self, x: float) -> str | None:
        if self._trim is None:
            return None
        start, end = (abs(self.x_at(t) - x) for t in self._trim)
        if min(start, end) > TRIM_GRAB:
            return None
        return "start" if start <= end else "end"

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._duration <= 0:
            return
        x = event.position().x()
        self._dragging = self._edge_at(x)
        if self._dragging is None:
            self.seek_requested.emit(min(self._duration, self.time_at(x)))

    def mouseMoveEvent(self, event) -> None:
        x = event.position().x()
        if self._dragging is None:
            if self._trim is not None:
                near = self._edge_at(x) is not None
                self.setCursor(Qt.CursorShape.SplitHCursor if near else Qt.CursorShape.PointingHandCursor)
            return
        t = min(self._duration, self.time_at(x))
        start, end = self._trim
        if self._dragging == "start":
            start = max(0.0, min(t, end - MIN_TRIM))
        else:
            end = min(self._duration, max(t, start + MIN_TRIM))
        self._trim = (start, end)
        self.update()
        self.trim_changed.emit(start, end)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = None


class _OctaveLabels(QWidget):
    """C2, C3… beside the roll, lined up with its rows."""

    def __init__(self, roll: PianoRoll, parent: QWidget):
        super().__init__(parent)
        self.roll = roll
        roll.range_changed.connect(self.update)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        colors = _colors(self)
        p.fillRect(self.rect(), colors["background"])
        low, high = self.roll.pitch_range
        row_h = self.height() / (high - low + 1)
        for pitch in range(low, high + 1):
            if is_black(pitch):
                p.fillRect(QRectF(0, (high - pitch) * row_h, self.width(), row_h), colors["black_row"])
        font = QFont(self.font())
        font.setPointSizeF(9.0)
        p.setFont(font)
        p.setPen(colors["label"])
        text_h = p.fontMetrics().height()
        for pitch in range(low, high + 1):
            if pitch % 12 == 0:
                middle = (high - pitch + 0.5) * row_h
                top = min(max(0.0, middle - text_h / 2), self.height() - text_h)
                rect = QRectF(0, top, self.width() - 5, text_h)
                p.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"C{pitch // 12 - 1}")
        p.setPen(QPen(colors["line"], 1))
        p.drawLine(QPointF(self.width() - 0.5, 0), QPointF(self.width() - 0.5, self.height()))
        p.end()


class PianoRollView(QScrollArea):
    """Scrolls the roll sideways and keeps the playhead in view."""

    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.roll = PianoRoll()
        self.setWidget(self.roll)
        self.setWidgetResizable(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.StyledPanel)
        self.setViewportMargins(GUTTER, 0, 0, 0)
        self._labels = _OctaveLabels(self.roll, self)
        self.roll.seek_requested.connect(self.seek_requested)
        self.follow = True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        viewport = self.viewport().geometry()
        self._labels.setGeometry(viewport.left() - GUTTER, viewport.top(), GUTTER, viewport.height())
        self.roll.setFixedHeight(self.viewport().height())
        self.roll.set_viewport_width(self.viewport().width())

    def set_position(self, t: float | None) -> None:
        self.roll.set_position(t)
        if t is None or not self.follow:
            return
        bar = self.horizontalScrollBar()
        x = self.roll.x_at(t)
        view = self.viewport().width()
        if x < bar.value() or x > bar.value() + view * 0.85:
            bar.setValue(int(x - view * 0.15))

    def show_time(self, t: float) -> None:
        bar = self.horizontalScrollBar()
        bar.setValue(int(self.roll.x_at(t) - self.viewport().width() * 0.15))

    def wheelEvent(self, event) -> None:
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self._zoom_at(1.15 if event.angleDelta().y() > 0 else 1 / 1.15, event.position().x())
            return
        delta = event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta() / 2
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - (delta.x() if abs(delta.x()) > abs(delta.y()) else delta.y()))

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.NativeGesture and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self._zoom_at(1 + event.value(), event.position().x())
            return True
        return super().event(event)

    def _zoom_at(self, factor: float, viewport_x: float) -> None:
        bar = self.horizontalScrollBar()
        t = self.roll.time_at(bar.value() + viewport_x)
        self.roll.zoom(factor)
        bar.setValue(int(self.roll.x_at(t) - viewport_x))
