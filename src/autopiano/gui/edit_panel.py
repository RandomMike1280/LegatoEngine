"""The Edit tab: trim a script, move it up or down, change its tempo, leave parts or
keys out, and save the result to the library.

The piano roll keeps the script's own timeline: the trimmed-off parts are shaded and
their edges can be dragged, while Listen plays the edited script at its new tempo.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..arrange.edit import MAX_TEMPO, MIN_TEMPO, PART_NAMES, EditError, Edits, edit_script
from ..format.apno import EXTENSION, ApnoError, read_script, write_script
from ..layout import list_layouts, load_layout
from ..models import Script
from ..paths import LIBRARY_DIR, safe_filename
from .piano_roll import PianoRollView
from .preview import ListenControls, ListenState, PreviewPlayer
from .widgets import Legend, move_to_trash, script_summary, secondary_label, title_label


class TimeBox(QDoubleSpinBox):
    """Seconds, shown as m:ss.ss. Typing plain seconds works too."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setDecimals(2)
        self.setSingleStep(0.5)
        self.setKeyboardTracking(False)
        self.setAccelerated(True)

    def textFromValue(self, value: float) -> str:
        minutes, hundredths = divmod(round(value * 100), 6000)
        return f"{minutes}:{hundredths / 100:05.2f}"

    def valueFromText(self, text: str) -> float:
        minutes, _, seconds = text.strip().rpartition(":")
        return 60 * int(minutes or 0) + float(seconds or 0)

    def validate(self, text: str, pos: int) -> QValidator.State:
        text = text.strip()
        if re.fullmatch(r"(\d+:)?\d+(\.\d{1,2})?", text) and (":" not in text or float(text.rpartition(":")[2]) < 60):
            fits = self.minimum() <= self.valueFromText(text) <= self.maximum()
            return QValidator.State.Acceptable if fits else QValidator.State.Intermediate
        return QValidator.State.Intermediate if re.fullmatch(r"\d*:?\d*\.?\d{0,2}", text) else QValidator.State.Invalid


class SemitoneBox(QSpinBox):
    """Semitones with their sign: +2, -3."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, minimum=-24, maximum=24)
        self.valueChanged.connect(lambda v: self.setSuffix(" semitone" if abs(v) == 1 else " semitones"))
        self.setSuffix(" semitones")

    def textFromValue(self, value: int) -> str:
        return f"{value:+d}" if value else "0"


class EditPanel(QWidget):
    saved = Signal(str)  # path of the saved script

    def __init__(self, preview: PreviewPlayer, parent: QWidget | None = None):
        super().__init__(parent)
        self.preview = preview
        self._original: Script | None = None
        self._path: Path | None = None
        self._edited: Script | None = None  # what Listen plays and Save writes
        self._view: Script | None = None  # the edit without trimming or tempo, drawn on the roll
        self._cursor: float | None = None  # the playhead, in the original script's time
        self._listening = (0.0, 1.0)  # trim start and tempo of the version being listened to
        self._reedit = QTimer(self, singleShot=True, interval=120)
        self._reedit.timeout.connect(self._apply)

        # ---- left column: what to change
        self.source_label = secondary_label("Pick a script in the Play tab and press Edit, or open one here.")
        open_button = QPushButton("Open…")
        script_box = QGroupBox("Script")
        script_row = QHBoxLayout(script_box)
        script_row.addWidget(self.source_label, 1)
        script_row.addWidget(open_button)

        self.start, self.end = TimeBox(), TimeBox()
        self.start_here, self.end_here = QPushButton("Here"), QPushButton("Here")
        for button in (self.start_here, self.end_here):
            button.setToolTip("Use the playhead's time. Click the piano roll to move it, or stop Listen there.")
        self.trim_silence = QPushButton("Trim the silence")
        self.trim_silence.setToolTip("Start at the first note and stop after the last one")
        trim_box = QGroupBox("Trim")
        trim_form = QFormLayout(trim_box)
        for label, box, here in (("Start", self.start, self.start_here), ("End", self.end, self.end_here)):
            row = QHBoxLayout()
            row.addWidget(box, 1)
            row.addWidget(here)
            trim_form.addRow(label, row)
        trim_form.addRow("", self.trim_silence)
        trim_form.addRow(secondary_label("Or drag the edges on the piano roll."))

        self.transpose = SemitoneBox()
        self.tempo = QSpinBox(minimum=round(MIN_TEMPO * 100), maximum=round(MAX_TEMPO * 100), singleStep=5, suffix="%")
        self.tempo_label = secondary_label()
        self.tempo_label.setWordWrap(False)
        self.parts = {role: QCheckBox(name.capitalize()) for role, name in PART_NAMES.items()}
        self.max_keys = QSpinBox(minimum=0, maximum=10, suffix=" keys at once")
        self.max_keys.setSpecialValueText("As many as now")
        self.layout_choice = QComboBox()
        for layout in list_layouts():
            self.layout_choice.addItem(layout.name, layout.id)
        change_box = QGroupBox("Change")
        form = QFormLayout(change_box)
        form.addRow("Transpose", self.transpose)
        tempo_row = QHBoxLayout()
        tempo_row.addWidget(self.tempo, 1)
        tempo_row.addWidget(self.tempo_label)
        form.addRow("Tempo", tempo_row)
        parts_row = QHBoxLayout()
        for box in self.parts.values():
            parts_row.addWidget(box)
        parts_row.addStretch(1)
        form.addRow("Play", parts_row)
        form.addRow("At most", self.max_keys)
        form.addRow("Piano", self.layout_choice)

        self.title = QLineEdit(placeholderText="Script name")
        self.reset_button = QPushButton("Reset")
        self.save_button = QPushButton("Save to Library")
        self.save_button.setDefault(True)
        self.status = secondary_label()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        name_row.addWidget(self.title, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.save_button, 1)

        left = QVBoxLayout()
        left.addWidget(script_box)
        left.addWidget(trim_box)
        left.addWidget(change_box)
        left.addLayout(name_row)
        left.addLayout(buttons)
        left.addWidget(self.status)
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(340)

        # ---- right column: the result
        self.result_title = title_label("No script open")
        self.result_info = secondary_label(
            "Trim a script, move it up or down, change its tempo or leave parts out. "
            "The original stays as it is unless you save over it."
        )
        self.roll = PianoRollView()
        self.listen = ListenControls(preview, self, lambda: self._listen(self._cursor))
        bottom = QHBoxLayout()
        bottom.addWidget(Legend())
        bottom.addStretch(1)
        bottom.addWidget(self.listen)
        right = QVBoxLayout()
        right.addWidget(self.result_title)
        right.addWidget(self.result_info)
        right.addWidget(self.roll, 1)
        right.addLayout(bottom)

        layout = QHBoxLayout(self)
        layout.addWidget(left_widget)
        layout.addLayout(right, 1)

        open_button.clicked.connect(self._open_dialog)
        self.start.valueChanged.connect(self._trim_typed)
        self.end.valueChanged.connect(self._trim_typed)
        self.start_here.clicked.connect(lambda: self._cursor is not None and self.start.setValue(self._cursor))
        self.end_here.clicked.connect(lambda: self._cursor is not None and self.end.setValue(self._cursor))
        self.trim_silence.clicked.connect(self._trim_to_notes)
        for signal in (
            self.transpose.valueChanged,
            self.tempo.valueChanged,
            self.max_keys.valueChanged,
            self.layout_choice.currentIndexChanged,
            *(box.toggled for box in self.parts.values()),
        ):
            signal.connect(self._changed)
        self.title.textEdited.connect(self._title_edited)
        self.reset_button.clicked.connect(self.reset)
        self.save_button.clicked.connect(self.save)
        self.roll.seek_requested.connect(self._seek)
        self.roll.roll.trim_changed.connect(self._trim_dragged)
        preview.position_changed.connect(self._preview_position)
        preview.state_changed.connect(self._preview_state)
        self._update_controls()

    # ---- opening

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open a script", str(LIBRARY_DIR), f"AutoPiano scripts (*{EXTENSION})")
        if path:
            self.load(path)

    def load(self, path: str | Path) -> None:
        try:
            script = read_script(path)
        except ApnoError as e:
            QMessageBox.warning(self, "Couldn't open this script", str(e))
            return
        if self.preview.owner is self:
            self.preview.stop()
        self._original, self._path, self._cursor = script, Path(path), None
        self.source_label.setText(Path(path).name)
        self.source_label.setToolTip(str(path))
        self.roll.set_position(None)
        self.roll.show_time(0.0)
        self.reset()

    def reset(self) -> None:
        """Back to the script as it was opened."""
        if self._original is None:
            return
        meta = self._original.meta
        controls = (self.start, self.end, self.transpose, self.tempo, self.max_keys, self.layout_choice, *self.parts.values())
        for control in controls:
            control.blockSignals(True)
        for box in (self.start, self.end):
            box.setRange(0.0, meta.duration)
        self.start.setValue(0.0)
        self.end.setValue(meta.duration)
        self.transpose.setValue(0)
        self.tempo.setValue(100)
        self.max_keys.setValue(0)
        self.layout_choice.setCurrentIndex(max(0, self.layout_choice.findData(meta.layout_id)))
        for box in self.parts.values():
            box.setChecked(True)
        for control in controls:
            control.blockSignals(False)
        self.title.setText(meta.title)
        self.status.setText("")
        self._apply()

    # ---- editing

    def edits(self) -> Edits:
        meta = self._original.meta
        end = self.end.value()
        layout_id = self.layout_choice.currentData()
        return Edits(
            start=self.start.value(),
            end=None if end >= meta.duration - 0.005 else end,
            transpose=self.transpose.value(),
            tempo=self.tempo.value() / 100,
            parts=frozenset(role for role, box in self.parts.items() if box.isChecked()),
            max_keys=self.max_keys.value(),
            layout_id=None if layout_id == meta.layout_id else layout_id,
            title=self.title.text().strip() or None,
        )

    def _changed(self) -> None:
        self._reedit.start()

    def _trim_typed(self) -> None:
        if self._original is not None:
            self.roll.roll.set_trim(self.start.value(), self.end.value())
            self._reedit.start()

    def _trim_dragged(self, start: float, end: float) -> None:
        for box, value in ((self.start, start), (self.end, end)):
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        self._reedit.start()

    def _trim_to_notes(self) -> None:
        if self._view is None or not self._view.notes:
            return
        first = min(n.start for n in self._view.notes)
        last = max(n.end for n in self._view.notes)
        self.start.setValue(math.floor(first * 100) / 100)  # rounding up would cut the first note
        self.end.setValue(math.ceil(last * 100) / 100)

    def _apply(self) -> None:
        self._reedit.stop()
        if self._original is None:
            return
        if self.preview.owner is self:
            self.preview.stop()
        edits = self.edits()
        meta = self._original.meta
        self.tempo_label.setText(f"{meta.bpm:.0f} → {meta.bpm * edits.tempo:.0f} BPM" if meta.bpm else "")
        try:
            edited = edit_script(self._original, edits)
            view = edit_script(self._original, replace(edits, start=0.0, end=None, tempo=1.0))
        except EditError as e:
            self._edited = None
            self.result_info.setText(str(e))
            self._update_controls()
            return
        self._edited, self._view = edited, view
        layout = load_layout(view.meta.layout_id)
        self.roll.roll.set_notes(view.notes, meta.duration, layout.low, layout.high, self._original.beats)
        self.roll.roll.set_trim(edits.start, edits.end)
        self.result_title.setText(edited.meta.title)
        changes = edits.describe()
        changes = changes[0].upper() + changes[1:] + "." if changes else "No changes yet."
        self.result_info.setText(f"{script_summary(edited)}\n{changes}")
        self._update_controls()

    def _title_edited(self, text: str) -> None:
        if self._edited is not None:
            self._edited.meta.title = text.strip() or self._original.meta.title
            self.result_title.setText(self._edited.meta.title)

    def _update_controls(self) -> None:
        has_script = self._original is not None
        for control in (
            self.start,
            self.end,
            self.trim_silence,
            self.transpose,
            self.tempo,
            self.max_keys,
            self.layout_choice,
            self.title,
            self.reset_button,
            *self.parts.values(),
        ):
            control.setEnabled(has_script)
        for button in (self.start_here, self.end_here):
            button.setEnabled(has_script and self._cursor is not None)
        self.save_button.setEnabled(self._edited is not None)
        self.listen.button.setEnabled(self._edited is not None)

    # ---- listening

    def _seek(self, t: float) -> None:
        self._cursor = t
        self.roll.set_position(t)
        self._update_controls()
        if self.listen.state in (ListenState.PLAYING, ListenState.LOADING):
            self._listen(t)
        elif self.listen.state is ListenState.PAUSED:
            self.preview.stop()  # Listen starts again from the click

    def _listen(self, at: float | None) -> None:
        if self._reedit.isActive():
            self._apply()
        if self._edited is None:
            return
        edits = self.edits()
        end = edits.end if edits.end is not None else self._original.meta.duration
        begin = (at - edits.start) / edits.tempo if at is not None and edits.start <= at < end - 0.1 else 0.0
        self._listening = (edits.start, edits.tempo)
        self.listen.play(self._edited.notes, start=begin)

    def _preview_position(self, t: float) -> None:
        if self.preview.owner is self:
            start, tempo = self._listening
            self._cursor = start + t * tempo  # Pause or Stop leaves the playhead here, ready for Here
            self.roll.set_position(self._cursor)
            if not self.start_here.isEnabled():
                self._update_controls()

    def _preview_state(self) -> None:
        if self.listen.state is ListenState.STOPPED and self.preview.owner is self:
            self.roll.set_position(self._cursor)

    # ---- saving

    def save(self) -> None:
        if self._reedit.isActive():
            self._apply()
        if self._edited is None:
            return
        title = self.title.text().strip() or self._edited.meta.title or "Untitled"
        self._edited.meta.title = title
        path = LIBRARY_DIR / (safe_filename(title) + EXTENSION)
        if path.exists():
            if self._path is not None and path.resolve() == self._path.resolve():
                question = f"This saves over “{path.name}”, the script you're editing. The original goes to the Trash."
            else:
                question = f"“{path.name}” is already in your library. Replace it? The old one goes to the Trash."
            box = QMessageBox(QMessageBox.Icon.Question, "Replace script?", question, QMessageBox.StandardButton.Cancel, self)
            replace_button = box.addButton("Replace", QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is not replace_button:
                return
            if error := move_to_trash(path):
                QMessageBox.warning(self, "Couldn't replace the script", error)
                return
        try:
            write_script(self._edited, path)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", f"The script couldn't be saved: {e.strerror}")
            return
        self.status.setText(f"Saved “{path.name}” to your library.")
        self.saved.emit(str(path))
