"""Plays a script on the built-in felt piano so it can be checked by ear. The audio is made on a
background thread (a long piece takes a second or two), so the window never waits for it.

Each tab has the same controls (ListenControls): ▶ Listen, which turns into ❚❚ Pause and
▶ Continue, a ■ to stop, and Sustain. Space pauses and continues anywhere in the window."""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from ..models import Note
from ..synth import SAMPLE_RATE, render_felt

KEPT = 2  # versions of the audio kept, so turning Sustain off and on again is instant


class ListenState(Enum):
    STOPPED = "stopped"
    LOADING = "loading"  # the audio is being made; it plays as soon as it's ready
    PLAYING = "playing"
    PAUSED = "paused"


class PreviewPlayer(QObject):
    position_changed = Signal(float)
    state_changed = Signal()
    sustain_changed = Signal(bool)
    failed = Signal(str)  # the audio couldn't start after it was made
    _rendered = Signal(object, bool, object)  # from the render thread: notes, sustain, and their audio or the error

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._made: list[tuple[list[Note], bool, object]] = []  # (notes, sustain, audio), newest first
        self._rendering: list[tuple[list[Note], bool]] = []  # being made into audio right now
        self._notes: list[Note] | None = None  # what is being listened to
        self._at = 0.0  # where it starts once loaded, or where it was paused
        self._origin = 0.0
        self._end = 0.0
        self._state = ListenState.STOPPED
        self._sustain = False
        self.owner: object | None = None  # the panel that started the preview
        self._rendered.connect(self._on_rendered)

    @property
    def state(self) -> ListenState:
        return self._state

    @property
    def sustain(self) -> bool:
        return self._sustain

    @property
    def position(self) -> float:
        """Seconds into the notes: where it's playing, paused, or about to start."""
        return time.monotonic() - self._origin if self._state is ListenState.PLAYING else self._at

    def play(self, notes: list[Note], start: float = 0.0, owner: object | None = None) -> str | None:
        """Starts playback: right away if these notes were heard last, otherwise as soon as their audio is made.
        Returns an error message, or None; an error after that comes through `failed`."""
        self.stop()
        self.owner = owner
        self._notes = notes
        return self._go(start)

    def pause(self) -> None:
        if self._state is ListenState.PLAYING:
            self._at = self.position
            self._silence()
            self._set_state(ListenState.PAUSED)
        elif self._state is ListenState.LOADING:
            self._set_state(ListenState.PAUSED)  # it waits where it would have started

    def resume(self) -> str | None:
        """Carries on from where it was paused. Returns an error message, or None."""
        return self._go(self._at) if self._state is ListenState.PAUSED else None

    def stop(self) -> None:
        if self._state is ListenState.PLAYING:
            self._silence()
        self._set_state(ListenState.STOPPED)

    def set_sustain(self, on: bool) -> None:
        """Lets every note ring on after its key is let go. While playing, the new sound takes over
        where the old one was, once it's made."""
        if on == self._sustain:
            return
        self._sustain = on
        self.sustain_changed.emit(on)
        if self._state in (ListenState.PLAYING, ListenState.LOADING):
            at = self.position
            if self._state is ListenState.PLAYING:
                self._silence()
            if error := self._go(at):
                self.failed.emit(error)

    def _go(self, start: float) -> str | None:
        """Plays self._notes from ``start`` once their audio, with the current sustain, is made."""
        notes, sustain = self._notes, self._sustain
        audio = next((a for n, s, a in self._made if n is notes and s == sustain), None)
        if audio is not None:
            error = self._start(audio, start)
            if error:
                self._set_state(ListenState.STOPPED)
            return error
        self._at = start
        self._set_state(ListenState.LOADING)
        if not any(n is notes and s == sustain for n, s in self._rendering):
            self._rendering.append((notes, sustain))
            threading.Thread(target=self._render, args=(notes, sustain), daemon=True).start()
        return None

    def _render(self, notes: list[Note], sustain: bool) -> None:
        try:
            audio = render_felt(notes, SAMPLE_RATE, sustain=sustain)
        except Exception as e:  # report it rather than leave the button waiting
            audio = e
        self._rendered.emit(notes, sustain, audio)

    def _on_rendered(self, notes: list[Note], sustain: bool, audio) -> None:
        self._rendering = [(n, s) for n, s in self._rendering if not (n is notes and s == sustain)]
        wanted = self._state is ListenState.LOADING and notes is self._notes and sustain == self._sustain
        if isinstance(audio, Exception):
            error = f"Couldn't make the preview: {audio}"
        else:
            self._made = [(notes, sustain, audio), *self._made][:KEPT]
            error = self._start(audio, self._at) if wanted else None
        if wanted and error:
            self._set_state(ListenState.STOPPED)
            self.failed.emit(error)

    def _start(self, audio, start: float) -> str | None:
        import sounddevice

        first = int(start * SAMPLE_RATE)
        if first >= len(audio):
            first, start = 0, 0.0
        try:
            sounddevice.play(audio[first:], SAMPLE_RATE)
        except Exception as e:
            return f"Couldn't play audio: {e}"
        self._origin = time.monotonic() - start
        self._end = len(audio) / SAMPLE_RATE
        self._timer.start()
        self._set_state(ListenState.PLAYING)
        return None

    def _silence(self) -> None:
        import sounddevice

        sounddevice.stop()
        self._timer.stop()

    def _set_state(self, state: ListenState) -> None:
        if state is not self._state:
            self._state = state
            self.state_changed.emit()

    def _tick(self) -> None:
        position = time.monotonic() - self._origin
        if position >= self._end:
            self.stop()
        else:
            self.position_changed.emit(position)


class ListenControls(QWidget):
    """One tab's ▶ Listen (then ❚❚ Pause and ▶ Continue), ■ to stop, and the Sustain switch.
    ``start`` begins listening, by calling play(); the tab picks the notes and where to start."""

    def __init__(
        self,
        preview: PreviewPlayer,
        owner: object,
        start: Callable[[], None],
        labels: tuple[str, str, str] = ("▶ Listen", "❚❚ Pause", "▶ Continue"),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.preview, self._owner, self._start, self._labels = preview, owner, start, labels
        self.button = QPushButton(labels[0])
        self.button.setToolTip("Hear the script on a soft piano. Space pauses and carries on.")
        self.stop_button = QPushButton("■")
        self.stop_button.setFixedWidth(self.stop_button.fontMetrics().horizontalAdvance("■") + 30)
        self.stop_button.setToolTip("Stop listening")
        self.stop_button.setAccessibleName("Stop listening")
        self.sustain = QCheckBox("Sustain")
        self.sustain.setToolTip(
            "Hear every note ring on after its key is let go, as if the sustain pedal were held down,\n"
            "like a Roblox piano with its sustain switch on. It only changes what you hear."
        )
        self.sustain.setChecked(preview.sustain)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.sustain)
        layout.addWidget(self.button)
        layout.addWidget(self.stop_button)
        self.button.clicked.connect(self.toggle)
        self.stop_button.clicked.connect(preview.stop)
        self.sustain.toggled.connect(preview.set_sustain)
        preview.sustain_changed.connect(self._sustain_changed)
        preview.state_changed.connect(self._update)
        self._update()

    @property
    def state(self) -> ListenState:
        """This tab's listening: stopped when another tab's preview is the one playing."""
        return self.preview.state if self.preview.owner is self._owner else ListenState.STOPPED

    def play(self, notes: list[Note], start: float = 0.0) -> None:
        self._report(self.preview.play(notes, start=start, owner=self._owner))

    def toggle(self) -> None:
        """What the button and Space do: listen, pause, or carry on."""
        state = self.state
        if state in (ListenState.PLAYING, ListenState.LOADING):
            self.preview.pause()
        elif state is ListenState.PAUSED:
            self._report(self.preview.resume())
        elif self.button.isEnabled():
            self._start()

    def _report(self, error: str | None) -> None:
        if error:
            QMessageBox.warning(self, "Couldn't play the preview", error)

    def _sustain_changed(self, on: bool) -> None:
        self.sustain.blockSignals(True)
        self.sustain.setChecked(on)
        self.sustain.blockSignals(False)

    def _update(self) -> None:
        state = self.state
        if state is ListenState.STOPPED:
            self.button.setText(self._labels[0])
        else:
            self.button.setText(self._labels[2] if state is ListenState.PAUSED else self._labels[1])
        self.stop_button.setVisible(state is not ListenState.STOPPED)


class SpaceListens(QObject):
    """Space pauses and carries on listening anywhere in ``window``, except while typing. It's caught
    before the focused widget sees it, so it never presses a button, such as ▶ Play, by accident."""

    TYPING = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)

    def __init__(self, window: QWidget, preview: PreviewPlayer, controls: Callable[[], ListenControls | None]):
        super().__init__(window)
        self._window, self._preview, self._controls = window, preview, controls
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
            and event.key() == Qt.Key.Key_Space
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and isinstance(obj, QWidget)
            and obj.window() is self._window
            and not self._typing()
        ):
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self._space()
            return True
        return False

    def _typing(self) -> bool:
        focus = QApplication.focusWidget()
        return focus is not None and (isinstance(focus, self.TYPING) or isinstance(focus.parent(), QAbstractSpinBox))

    def _space(self) -> None:
        if self._preview.state in (ListenState.PLAYING, ListenState.LOADING):
            self._preview.pause()  # whichever tab started it
        elif (controls := self._controls()) is not None:
            controls.toggle()
