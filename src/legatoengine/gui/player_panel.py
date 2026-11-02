"""The Play tab: the script library and the controls that play a script into Roblox."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..arrange.possible import make_possible
from ..format.apno import EXTENSION, ApnoError, read_script
from ..layout import load_layout
from ..library import SORTS, Entry, folders, scan, search, sort_entries
from ..models import Note, Script
from ..paths import LIBRARY_DIR
from ..player.engine import Player, State
from ..player.hotkeys import HOTKEYS, HotkeyListener
from ..player.keyboard import DryRunKeyboard, system_keyboard
from ..player.permissions import can_send_keys, open_accessibility_settings
from ..player.timeline import PlaySettings, build_timeline
from . import settings
from .piano_roll import PianoRollView
from .preview import ListenControls, ListenState, PreviewPlayer
from .widgets import SearchField, format_time, move_to_trash, script_summary, secondary_label, title_label


class _Bridge(QObject):
    """Carries player and hotkey events from their threads to the window's thread."""

    state = Signal(object)
    position = Signal(float)
    countdown = Signal(float)
    toggle = Signal()
    stop = Signal()


class PlayerPanel(QWidget):
    edit_requested = Signal(str)  # path of the script to open in the Edit tab

    def __init__(self, preview: PreviewPlayer, parent: QWidget | None = None):
        super().__init__(parent)
        self.preview = preview
        self._script: Script | None = None
        self._path: Path | None = None
        self._notes: list[Note] = []  # what Play and Listen use: the script's notes, or their keyboard-possible version
        self._start_at = 0.0
        self._status_note = ""  # a warning shown while playing, such as "Roblox isn't open"
        self._bridge = _Bridge()
        self.player = Player(
            DryRunKeyboard(),
            on_state=self._bridge.state.emit,
            on_position=self._bridge.position.emit,
            on_countdown=self._bridge.countdown.emit,
        )
        self.hotkeys = HotkeyListener({})

        # ---- library
        self._entries: list[Entry] = []  # every script in the library
        self._shown: list[Entry] = []  # the ones the search lets through, in list order
        self.search = SearchField("Search your library")
        self.search.setToolTip(
            "Type part of a song's name, its folder or its key, such as “fur elise”, “classical” or “a minor”.\n"
            "↑ and ↓ move through the results, Return opens the first one, Esc clears. ⌘F jumps here."
        )
        self.sort = QComboBox()
        for key, label in SORTS.items():
            self.sort.addItem(label, key)
        self.sort.setToolTip("While you search, the best matches come first.")
        self.count_label = secondary_label()
        self.count_label.setWordWrap(False)
        self.library = QListWidget()
        self.library.setAlternatingRowColors(True)
        self.library.setWordWrap(True)  # long titles wrap instead of hiding behind a sideways scroll bar
        self.library.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        open_button = QPushButton("Open…")
        reveal_button = QPushButton("Show in Finder")
        trash_button = QPushButton("Move to Trash")
        library_box = QGroupBox("Library")
        library_layout = QVBoxLayout(library_box)
        library_layout.addWidget(self.search)
        counts = QHBoxLayout()
        counts.addWidget(self.count_label, 1)
        counts.addWidget(self.sort)
        library_layout.addLayout(counts)
        library_layout.addWidget(self.library, 1)
        row = QHBoxLayout()
        row.addWidget(open_button)
        row.addWidget(reveal_button)
        library_layout.addLayout(row)
        library_layout.addWidget(trash_button)
        library_box.setFixedWidth(280)

        # ---- now playing
        self.title = title_label("Nothing selected")
        self.info = secondary_label("Save a script from the Convert tab, or open one.")
        self.roll = PianoRollView()
        self.play_button = QPushButton("▶ Play")
        self.play_button.setDefault(True)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("■ Stop")
        # "listening", so they aren't taken for the Roblox transport's Pause and Play
        self.listen = ListenControls(preview, self, self._listen, ("Listen", "❚❚ Pause listening", "▶ Continue listening"))
        self.edit_button = QPushButton("Edit")
        self.edit_button.setToolTip("Trim this script, move it up or down, change its tempo…")
        self.time_label = QLabel("0:00 / 0:00")
        self.start_label = secondary_label()
        self.start_label.setWordWrap(False)
        self.reset_start = QPushButton("From the beginning")
        self.reset_start.setFlat(True)
        transport = QHBoxLayout()
        for w in (self.play_button, self.pause_button, self.stop_button):
            transport.addWidget(w)
        transport.addSpacing(12)
        transport.addWidget(self.time_label)
        transport.addStretch(1)
        transport.addWidget(self.start_label)
        transport.addWidget(self.reset_start)
        transport.addWidget(self.listen)
        transport.addWidget(self.edit_button)

        self.speed = QSlider(Qt.Orientation.Horizontal, minimum=25, maximum=200, singleStep=5, pageStep=25)
        self.speed.setMinimumWidth(260)
        self.speed_label = QLabel()
        self.countdown = QSpinBox(minimum=0, maximum=10, suffix=" s")
        self.hold = QComboBox()
        self.hold.addItem("For each note's length", "natural")
        self.hold.addItem("Tap (let go right away)", "tap")
        self.focus_roblox = QCheckBox("Bring Roblox to the front when I press Play")
        self.test_mode = QCheckBox("Test mode: don't press any keys")
        self.possible = QCheckBox("Keyboard-possible mode")
        self.possible.setToolTip(
            "A real keyboard can't press lowercase and capital keys at the same moment (Shift changes them all),\n"
            "or Ctrl keys together with normal ones. With this on, every chord sticks to one of them:\n"
            "the melody's, or whichever keeps the most of the chord. Each note that would need another\n"
            "is played an octave away, swapped for a copy of another note of the chord, or left out.\n"
            "The piano roll and Listen show what will be played."
        )
        self.possible_note = secondary_label()
        self.possible_note.setWordWrap(False)
        self.hotkey_toggle = QComboBox()
        self.hotkey_stop = QComboBox()
        for combo in (self.hotkey_toggle, self.hotkey_stop):
            combo.addItems(list(HOTKEYS))
        options = QGroupBox("Playback")
        form = QFormLayout(options)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed, 1)
        speed_row.addWidget(self.speed_label)
        form.addRow("Speed", speed_row)
        form.addRow("Countdown", self.countdown)
        form.addRow("Hold keys", self.hold)
        possible_row = QHBoxLayout()
        possible_row.addWidget(self.possible)
        possible_row.addSpacing(8)
        possible_row.addWidget(self.possible_note, 1)
        form.addRow("", possible_row)
        form.addRow("", self.focus_roblox)
        form.addRow("", self.test_mode)
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(QLabel("Play / pause"))
        hotkey_row.addWidget(self.hotkey_toggle)
        hotkey_row.addSpacing(12)
        hotkey_row.addWidget(QLabel("Stop"))
        hotkey_row.addWidget(self.hotkey_stop)
        hotkey_row.addStretch(1)
        form.addRow("Hotkeys", hotkey_row)

        self.status = QLabel()
        self.status.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(self.title)
        right.addWidget(self.info)
        right.addWidget(self.roll, 1)
        right.addLayout(transport)
        right.addWidget(options)
        right.addWidget(self.status)

        layout = QHBoxLayout(self)
        layout.addWidget(library_box)
        layout.addLayout(right, 1)

        # New, changed and removed scripts show up by themselves, a moment after the folder changes.
        self._watcher = QFileSystemWatcher(self)
        self._rescan = QTimer(self, singleShot=True, interval=400)
        self._rescan.timeout.connect(self.refresh)
        self._watcher.directoryChanged.connect(lambda _folder: self._rescan.start())

        self._restore_settings()
        self.library.currentItemChanged.connect(self._selected)
        self.search.textChanged.connect(lambda _text: self._populate())
        self.search.returnPressed.connect(self._open_top_result)
        self.search.moved.connect(self._move_selection)
        self.sort.currentIndexChanged.connect(self._sort_changed)
        open_button.clicked.connect(self._open_dialog)
        reveal_button.clicked.connect(self._reveal)
        trash_button.clicked.connect(self._trash)
        self.play_button.clicked.connect(lambda: self.play(from_hotkey=False))
        self.pause_button.clicked.connect(self.player.toggle_pause)
        self.stop_button.clicked.connect(self.player.stop)
        self.edit_button.clicked.connect(self._edit)
        self.reset_start.clicked.connect(lambda: self._set_start(0.0))
        self.roll.seek_requested.connect(self._set_start)
        self.speed.valueChanged.connect(self._options_changed)
        for signal in (
            self.countdown.valueChanged,
            self.hold.currentIndexChanged,
            self.focus_roblox.toggled,
            self.test_mode.toggled,
            self.possible.toggled,
        ):
            signal.connect(self._options_changed)
        self.possible.toggled.connect(self._possible_toggled)
        self.hotkey_toggle.currentIndexChanged.connect(self._hotkeys_changed)
        self.hotkey_stop.currentIndexChanged.connect(self._hotkeys_changed)
        self._bridge.state.connect(self._on_state)
        self._bridge.position.connect(self._on_position)
        self._bridge.countdown.connect(self._on_countdown)
        self._bridge.toggle.connect(self._hotkey_toggle)
        self._bridge.stop.connect(self.player.stop)
        preview.position_changed.connect(self._preview_position)
        preview.state_changed.connect(self._preview_state)

        self._options_changed()
        self._hotkeys_changed()
        self.refresh()
        self._on_state(State.STOPPED)

    # ---- settings

    def _restore_settings(self) -> None:
        self.speed.setValue(settings.load("play/speed", 100))
        self.countdown.setValue(settings.load("play/countdown", 3))
        self.hold.setCurrentIndex(max(0, self.hold.findData(settings.load("play/hold", "natural"))))
        self.focus_roblox.setChecked(settings.load("play/focus_roblox", True))
        self.test_mode.setChecked(settings.load("play/test_mode", False))
        self.possible.setChecked(settings.load("play/possible", False))
        self.hotkey_toggle.setCurrentText(settings.load("play/hotkey_toggle", "F6"))
        self.hotkey_stop.setCurrentText(settings.load("play/hotkey_stop", "F7"))
        self.sort.setCurrentIndex(max(0, self.sort.findData(settings.load("play/sort", "newest"))))

    def _options_changed(self) -> None:
        self.speed_label.setText(f"{self.speed.value()}%")
        settings.save("play/speed", self.speed.value())
        settings.save("play/countdown", self.countdown.value())
        settings.save("play/hold", self.hold.currentData())
        settings.save("play/focus_roblox", self.focus_roblox.isChecked())
        settings.save("play/test_mode", self.test_mode.isChecked())
        settings.save("play/possible", self.possible.isChecked())

    def _hotkeys_changed(self) -> None:
        toggle, stop = self.hotkey_toggle.currentText(), self.hotkey_stop.currentText()
        if toggle == stop:
            self._show_status("Play/pause and stop need different hotkeys.")
            return
        settings.save("play/hotkey_toggle", toggle)
        settings.save("play/hotkey_stop", stop)
        self.hotkeys.set_bindings({toggle: self._bridge.toggle.emit, stop: self._bridge.stop.emit})
        self._idle_status()

    def start_hotkeys(self) -> bool:
        """Starts listening for hotkeys, or upgrades a listen-only tap once Accessibility is allowed."""
        if self.hotkeys.active and not self.hotkeys.swallows and can_send_keys():
            self.hotkeys.stop()
        started = self.hotkeys.start()
        if self.player.state is State.STOPPED:
            self._idle_status()
        return started

    # ---- library

    def refresh(self, select: str | None = None) -> None:
        """Re-reads the library folder. ``select`` opens that script, unless one is playing."""
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        self._watch()
        if self.player.state is not State.STOPPED:
            select = None
        self._entries = scan()
        if select and not search([e for e in self._entries if str(e.path) == select], self.search.text()):
            self.search.blockSignals(True)  # a search that hides the new script would leave it out of the list
            self.search.clear()
            self.search.blockSignals(False)
        self._populate(keep_scroll=select is None)
        if select:
            self.load(Path(select))
        elif self._path is None and self._shown:
            self.library.setCurrentRow(0)  # opens it through _selected

    def _populate(self, keep_scroll: bool = False) -> None:
        """Lists the scripts that match the search, with the open one selected."""
        query = self.search.text().strip()
        self._shown = search(sort_entries(self._entries, self.sort.currentData()), query)
        scroll = self.library.verticalScrollBar().value()
        current = str(self._path) if self._path else None
        self.library.blockSignals(True)
        self.library.clear()
        for entry in self._shown:
            details = [format_time(entry.duration), entry.key_name] if entry.readable else ["(can't be read)"]
            if entry.folder:
                details.append(entry.folder)
            item = QListWidgetItem(f"{entry.title}\n{' · '.join(d for d in details if d)}")
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path))
            item.setToolTip(str(entry.path))
            self.library.addItem(item)
            if str(entry.path) == current:
                self.library.setCurrentItem(item)
        if not self._shown:
            if query and self._entries:
                note = f"Nothing matches “{query}”.\nCheck the spelling, or try fewer words."
            else:
                note = "No scripts yet.\nConvert a song to add one."
            placeholder = QListWidgetItem(note)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.library.addItem(placeholder)
        if keep_scroll:
            self.library.verticalScrollBar().setValue(scroll)
        elif self.library.currentItem() is not None:
            self.library.scrollToItem(self.library.currentItem())
        else:
            self.library.scrollToTop()
        self.library.blockSignals(False)
        total = len(self._entries)
        if query:
            self.count_label.setText(f"{len(self._shown)} of {total}")
        else:
            self.count_label.setText(f"{total} script{'s' if total != 1 else ''}")

    def _watch(self) -> None:
        wanted = {str(folder) for folder in folders()}
        watched = set(self._watcher.directories())
        if watched - wanted:
            self._watcher.removePaths(sorted(watched - wanted))
        if wanted - watched:
            self._watcher.addPaths(sorted(wanted - watched))

    def _sort_changed(self) -> None:
        settings.save("play/sort", self.sort.currentData())
        self._populate()

    def _move_selection(self, step: int) -> None:
        """↑ and ↓ in the search box: opens the next or previous result."""
        if not self._shown:
            return
        row = self.library.currentRow()
        if row < 0:
            row = 0 if step > 0 else len(self._shown) - 1
        else:
            row = max(0, min(len(self._shown) - 1, row + step))
        self.library.setCurrentRow(row)  # opens it through _selected

    def _open_top_result(self) -> None:
        """Return in the search box opens the best match, unless a result is already open."""
        if self._shown and self.library.currentRow() < 0:
            self.library.setCurrentRow(0)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _selected(self, item: QListWidgetItem | None, _previous=None) -> None:
        if item is not None and item.data(Qt.ItemDataRole.UserRole):
            self.load(Path(item.data(Qt.ItemDataRole.UserRole)))

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open a script", str(LIBRARY_DIR), f"AutoPiano scripts (*{EXTENSION})")
        if path:
            self.load(Path(path))

    def _reveal(self) -> None:
        target = self._path if self._path and self._path.exists() else LIBRARY_DIR
        subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])

    def _trash(self) -> None:
        item = self.library.currentItem()
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        answer = QMessageBox.question(self, "Move to Trash?", f"Move “{path.name}” to the Trash?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        error = move_to_trash(path)
        if error:
            QMessageBox.warning(self, "Couldn't move to Trash", error)
            return
        if self._path == path:
            self._clear()
        self.refresh()

    def load(self, path: Path) -> None:
        if self.player.state is not State.STOPPED:
            self.player.stop()
        try:
            script = read_script(path)
        except (ApnoError, OSError) as e:
            QMessageBox.warning(self, "Couldn't open this script", str(e))
            return
        if self.preview.owner is self:
            self.preview.stop()
        self._script, self._path = script, path
        self._select_in_library(path)
        layout = load_layout(script.meta.layout_id)
        self.title.setText(script.meta.title or path.stem)
        self.info.setText(f"{script_summary(script)}  ·  {layout.name}")
        self._choose_notes()
        self._set_start(0.0)
        self._on_state(State.STOPPED)

    def open_file(self, path: str) -> None:
        self.load(Path(path))

    def _select_in_library(self, path: Path) -> None:
        """Highlights the open script in the list, or nothing when it lives elsewhere."""
        self.library.blockSignals(True)
        self.library.setCurrentItem(None)
        for row in range(self.library.count()):
            item = self.library.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == str(path):
                self.library.setCurrentItem(item)
                self.library.scrollToItem(item)
                break
        self.library.blockSignals(False)

    def _choose_notes(self) -> None:
        """Picks the notes Play and Listen use, and shows them in the piano roll."""
        script = self._script
        if script is None:
            self._notes = []
            self.possible_note.setText("")
            return
        layout = load_layout(script.meta.layout_id)
        if self.possible.isChecked():
            self._notes, report = make_possible(script.notes, layout)
            if report.chords:
                self.possible_note.setText(f"{report.chords} of {script.chord_count} chords changed")
            else:
                self.possible_note.setText("Every chord can already be pressed")
        else:
            self._notes = script.notes
            self.possible_note.setText("")
        self.roll.roll.set_notes(self._notes, script.meta.duration, layout.low, layout.high, script.beats)

    def _possible_toggled(self) -> None:
        if self.preview.owner is self:
            self.preview.stop()  # what it was playing is no longer what Play would press
        self._choose_notes()

    def _clear(self) -> None:
        self._script = self._path = None
        self._choose_notes()
        self.title.setText("Nothing selected")
        self.info.setText("Save a script from the Convert tab, or open one.")
        self.roll.roll.clear()
        self._on_state(State.STOPPED)

    # ---- playing

    def play(self, from_hotkey: bool) -> None:
        if self._script is None:
            return
        if self.player.state is State.PAUSED:
            self.player.resume()
            return
        if self.player.state is not State.STOPPED:
            return
        test = self.test_mode.isChecked()
        if not test and not can_send_keys():
            self._explain_permission()
            return
        self.preview.stop()
        settings_ = PlaySettings(speed=self.speed.value() / 100, hold=self.hold.currentData())
        actions = build_timeline(self._notes, settings_)
        self.player.keyboard = DryRunKeyboard() if test else system_keyboard()
        self.player.load(actions, speed=settings_.speed)
        self._status_note = ""
        if not from_hotkey and not test and self.focus_roblox.isChecked():
            from ..player.focus import focus_roblox

            if not focus_roblox():
                self._status_note = "Roblox isn't open, so keys go to whichever app is in front. "
        self.player.play(start=self._start_at, countdown=0.3 if from_hotkey else self.countdown.value())

    def _edit(self) -> None:
        if self._path is not None:
            self.edit_requested.emit(str(self._path))

    def _hotkey_toggle(self) -> None:
        if self.player.state is State.STOPPED:
            self.play(from_hotkey=True)
        else:
            self.player.toggle_pause()

    def _set_start(self, t: float) -> None:
        self._start_at = t
        self.start_label.setText(f"Starts at {format_time(t)}" if t > 0 else "")
        self.reset_start.setVisible(t > 0)
        if self.listen.state is ListenState.PAUSED:
            self.preview.stop()  # Listen starts again from the new start
        if self.player.state is State.STOPPED and self.listen.state is ListenState.STOPPED:
            self.roll.set_position(t if t > 0 else None)
            self._update_time(t)

    def _explain_permission(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Allow AutoPiano to press keys")
        box.setText("To play in Roblox, AutoPiano needs the Accessibility permission.")
        box.setInformativeText(
            "In System Settings → Privacy & Security → Accessibility, turn on AutoPiano "
            "(or the Terminal app, if you started AutoPiano from Terminal). Then press Play again.\n\n"
            "Want to try it first? Turn on Test mode."
        )
        settings_button = box.addButton("Open System Settings", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is settings_button:
            open_accessibility_settings()

    # ---- player events (window thread)

    def _on_state(self, state: State) -> None:
        has_script = self._script is not None
        stopped = state is State.STOPPED
        self.play_button.setEnabled(has_script and (stopped or state is State.PAUSED))
        self.play_button.setText("▶ Resume" if state is State.PAUSED else "▶ Play")
        self.pause_button.setEnabled(state in (State.PLAYING, State.PAUSED))
        self.pause_button.setText("Resume" if state is State.PAUSED else "Pause")
        self.stop_button.setEnabled(not stopped)
        self.listen.button.setEnabled(has_script and stopped)
        self.edit_button.setEnabled(has_script)
        self.speed.setEnabled(stopped)
        self.hold.setEnabled(stopped)
        self.possible.setEnabled(stopped)
        self.test_mode.setEnabled(stopped)
        self.library.setEnabled(stopped)
        self.search.setEnabled(stopped)
        self.sort.setEnabled(stopped)
        toggle, stop = self.hotkey_toggle.currentText(), self.hotkey_stop.currentText()
        if state is State.PLAYING:
            self._show_status(f"{self._status_note}Playing. {toggle} pauses, {stop} stops.")
        elif state is State.PAUSED:
            self._show_status(f"Paused. {toggle} or Resume carries on.")
        elif state is State.STOPPED:
            if isinstance(self.player.keyboard, DryRunKeyboard) and self.player.keyboard.events:
                presses = sum(1 for _, _, down in self.player.keyboard.events if down)
                self._show_status(f"Test run finished: {presses} key presses would have been sent.")
                self.player.keyboard = DryRunKeyboard()
            else:
                self._idle_status()
            self.roll.set_position(self._start_at if self._start_at > 0 else None)
            self._update_time(self._start_at)

    def _on_position(self, t: float) -> None:
        self.roll.set_position(t)
        self._update_time(t)

    def _on_countdown(self, remaining: float) -> None:
        self._show_status(f"{self._status_note}Starting in {math.ceil(remaining)}… switch to Roblox now.")

    def _update_time(self, t: float) -> None:
        total = self._script.meta.duration if self._script else 0.0
        self.time_label.setText(f"{format_time(t)} / {format_time(total)}")

    def _idle_status(self) -> None:
        toggle, stop = self.hotkey_toggle.currentText(), self.hotkey_stop.currentText()
        if self._script is None:
            text = "Pick a script from your library."
        elif self.hotkeys.active:
            text = f"Ready. In Roblox, press {toggle} to start or pause and {stop} to stop."
            if toggle.startswith("F") or stop.startswith("F"):
                text += " On a MacBook keyboard, hold fn with the F-key."
        else:
            text = "Ready. Hotkeys are off until AutoPiano has the Accessibility permission."
        self._show_status(text)

    def _show_status(self, text: str) -> None:
        self.status.setText(text)

    # ---- listening

    def _listen(self) -> None:
        if self._script is not None:
            self.listen.play(self._notes, start=self._start_at)

    def _preview_position(self, t: float) -> None:
        if self.preview.owner is self:
            self.roll.set_position(t)
            self._update_time(t)

    def _preview_state(self) -> None:
        if self.listen.state is ListenState.STOPPED and self.preview.owner is self:
            self.roll.set_position(self._start_at if self._start_at > 0 else None)
            self._update_time(self._start_at)

    def shutdown(self) -> None:
        self.player.stop()
        self.hotkeys.stop()
