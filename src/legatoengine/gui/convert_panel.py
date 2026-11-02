"""The Convert tab: pick a song or paste a link, convert it, shape the arrangement, save the script.
Several songs or links at once go to the queue, which converts and saves them one after another."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..arrange.pipeline import PRESETS, ArrangeError, ArrangeSettings, arrange
from ..format.apno import EXTENSION, write_script
from ..ingest.convert import SOURCE_KINDS, is_midi
from ..ingest.download import find_links, is_link, with_scheme
from ..layout import list_layouts, load_layout
from ..models import Script, Song
from ..paths import LIBRARY_DIR, safe_filename
from . import settings
from .piano_roll import PianoRollView
from .preview import ListenControls, ListenState, PreviewPlayer
from .queue_box import QueueBox
from .widgets import DropZone, Legend, link_host, move_to_trash, script_summary, secondary_label, title_label
from .workers import ConvertJob

KEY_CHOICES = [("Easiest key", "auto"), ("Original key", "original"), ("Custom", "custom")]


class ConvertPanel(QWidget):
    saved = Signal(str)  # path of the saved script

    def __init__(self, preview: PreviewPlayer, parent: QWidget | None = None):
        super().__init__(parent)
        self.preview = preview
        self._path: Path | None = None  # the song file
        self._link: str | None = None  # a link to download first
        self._downloaded: str | None = None  # the link that _path came from
        self._song: Song | None = None
        self._script: Script | None = None
        self._job: ConvertJob | None = None
        self._rearrange = QTimer(self, singleShot=True, interval=250)
        self._rearrange.timeout.connect(self._arrange)

        # ---- left column: song and arrangement settings
        self.drop = DropZone()
        self.drop.file_chosen.connect(self.set_file)
        self.drop.link_chosen.connect(self.set_link)
        self.drop.songs_chosen.connect(self.queue_songs)
        self.link = QLineEdit(placeholderText="or paste links (YouTube, SoundCloud…)")
        self.link.setClearButtonEnabled(True)
        self.link.setToolTip(
            "Convert downloads the song first, into ~/Music/LegatoEngine/Downloads.\n"
            "Most video and music sites work, and so do direct links to audio files.\n"
            "Paste several links at once (a list, even a whole page of text) to queue them all."
        )
        self.link.returnPressed.connect(self.convert)
        self.link.textChanged.connect(self._link_changed)
        self.source = QComboBox()
        for kind, label in SOURCE_KINDS.items():
            self.source.addItem(label, kind)
        song_box = QGroupBox("Song")
        song_form = QVBoxLayout(song_box)
        song_form.addWidget(self.drop)
        song_form.addWidget(self.link)
        row = QHBoxLayout()
        row.addWidget(QLabel("Type"))
        row.addWidget(self.source, 1)
        song_form.addLayout(row)

        self.preset = QComboBox()
        for preset in PRESETS.values():
            self.preset.addItem(preset.label, preset.id)
        self.preset_help = secondary_label()
        self.layout_choice = QComboBox()
        for layout in list_layouts():
            self.layout_choice.addItem(layout.name, layout.id)
        self.key_mode = QComboBox()
        for label, value in KEY_CHOICES:
            self.key_mode.addItem(label, value)
        self.key_mode.setToolTip(
            "Easiest key moves the song up or down by up to 6 semitones so it needs\n"
            "as few black keys (Shift presses) as possible."
        )
        self.key_shift = QSpinBox(minimum=-11, maximum=11, suffix=" semitones")
        self.max_keys = QSpinBox(minimum=1, maximum=10, suffix=" keys")
        self.quantize = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100, singleStep=5, pageStep=25)
        self.quantize_label = QLabel()
        arrangement = QGroupBox("Arrangement")
        form = QFormLayout(arrangement)
        form.addRow("Style", self.preset)
        form.addRow("", self.preset_help)
        form.addRow("Piano", self.layout_choice)
        form.addRow("Key", self.key_mode)
        form.addRow("", self.key_shift)
        form.addRow("At most", self.max_keys)
        quantize_row = QHBoxLayout()
        quantize_row.addWidget(self.quantize, 1)
        quantize_row.addWidget(self.quantize_label)
        form.addRow("Snap to beat", quantize_row)

        self.title = QLineEdit(placeholderText="Script name")
        self.convert_button = QPushButton("Convert")
        self.convert_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.progress = QProgressBar(maximum=1000, textVisible=False)
        self.stage = secondary_label()
        buttons = QHBoxLayout()
        buttons.addWidget(self.convert_button, 1)
        buttons.addWidget(self.cancel_button)

        left = QVBoxLayout()
        left.addWidget(song_box)
        left.addWidget(arrangement)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        name_row.addWidget(self.title, 1)
        left.addLayout(name_row)
        left.addLayout(buttons)
        left.addWidget(self.progress)
        left.addWidget(self.stage)
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(340)

        # ---- right column: the result
        self.result_title = title_label("No song yet")
        self.result_info = secondary_label(
            "Choose a song or paste a link on the left. MIDI files convert instantly; audio takes a few minutes the first time."
        )
        self.roll = PianoRollView()
        self.listen = ListenControls(preview, self, self._listen)
        self.save_button = QPushButton("Save to Library")
        bottom = QHBoxLayout()
        bottom.addWidget(Legend())
        bottom.addStretch(1)
        bottom.addWidget(self.listen)
        bottom.addWidget(self.save_button)
        result = QWidget()
        right = QVBoxLayout(result)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.result_title)
        right.addWidget(self.result_info)
        right.addWidget(self.roll, 1)
        right.addLayout(bottom)
        self.queue = QueueBox(self._queue_settings, self._converting)  # hidden while empty
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(result)
        splitter.addWidget(self.queue)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QHBoxLayout(self)
        layout.addWidget(left_widget)
        layout.addWidget(splitter, 1)

        self._restore_settings()
        self.convert_button.clicked.connect(self.convert)
        self.cancel_button.clicked.connect(self.cancel)
        self.save_button.clicked.connect(self.save)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.key_mode.currentIndexChanged.connect(self._key_mode_changed)
        for signal in (
            self.layout_choice.currentIndexChanged,
            self.key_shift.valueChanged,
            self.max_keys.valueChanged,
            self.quantize.valueChanged,
            self.source.currentIndexChanged,
        ):
            signal.connect(self._settings_changed)
        self.title.textEdited.connect(self._title_edited)
        preview.position_changed.connect(self._preview_position)
        preview.state_changed.connect(self._preview_state)
        self._update_labels()
        self._set_busy(False)

    # ---- settings

    def _restore_settings(self) -> None:
        for combo, key, default in (
            (self.source, "convert/source", "auto"),
            (self.preset, "convert/preset", "full"),
            (self.layout_choice, "convert/layout", "vp61"),
            (self.key_mode, "convert/key_mode", "auto"),
        ):
            index = combo.findData(settings.load(key, default))
            combo.setCurrentIndex(max(0, index))
        self.key_shift.setValue(settings.load("convert/key_shift", 0))
        self.max_keys.setValue(settings.load("convert/max_keys", PRESETS[self.preset.currentData()].max_keys))
        self.quantize.setValue(settings.load("convert/quantize", 0))

    def _save_settings(self) -> None:
        settings.save("convert/source", self.source.currentData())
        settings.save("convert/preset", self.preset.currentData())
        settings.save("convert/layout", self.layout_choice.currentData())
        settings.save("convert/key_mode", self.key_mode.currentData())
        settings.save("convert/key_shift", self.key_shift.value())
        settings.save("convert/max_keys", self.max_keys.value())
        settings.save("convert/quantize", self.quantize.value())

    def arrange_settings(self) -> ArrangeSettings:
        mode = self.key_mode.currentData()
        return ArrangeSettings(
            preset=self.preset.currentData(),
            layout_id=self.layout_choice.currentData(),
            transpose=self.key_shift.value() if mode == "custom" else mode,
            max_keys=self.max_keys.value(),
            quantize=self.quantize.value() / 100,
        )

    def _preset_changed(self) -> None:
        self.max_keys.blockSignals(True)
        self.max_keys.setValue(PRESETS[self.preset.currentData()].max_keys)
        self.max_keys.blockSignals(False)
        self._settings_changed()

    def _key_mode_changed(self) -> None:
        self._settings_changed()

    def _settings_changed(self) -> None:
        self._update_labels()
        self._save_settings()
        if self._song is not None:
            self._rearrange.start()

    def _update_labels(self) -> None:
        self.preset_help.setText(PRESETS[self.preset.currentData()].description)
        self.key_shift.setVisible(self.key_mode.currentData() == "custom")
        value = self.quantize.value()
        self.quantize_label.setText("Off" if value == 0 else f"{value}%")

    # ---- converting

    def _reset(self) -> None:
        if self._job and self._job.running:
            self._job.cancel()
        self._path = self._link = self._downloaded = None
        self._song = None
        self._script = None
        self.preview.stop()
        self.roll.roll.clear()
        self.stage.setText("")
        self.progress.setValue(0)
        self._set_busy(False)

    def set_file(self, path: str) -> None:
        self._reset()
        self._path = Path(path)
        self.link.clear()
        self.drop.show_file(path)
        self.title.setText(self._path.stem)
        self.result_title.setText(self._path.stem)
        self.result_info.setText("Press Convert to turn this song into a script.")
        if is_midi(self._path):
            self.convert()  # MIDI is instant

    def set_link(self, url: str) -> None:
        """A song to download: Convert downloads it, then converts it as usual."""
        self._reset()
        self._link = url.strip()
        self.link.setText(self._link)
        self.drop.show_link(self._link)
        self.title.clear()
        self.result_title.setText(f"A song from {link_host(self._link)}")
        self.result_info.setText("Press Convert to download this song and turn it into a script.")

    def queue_songs(self, sources: list[str]) -> None:
        """Converts these songs or links one after another, saving each to the library."""
        self.queue.add(sources)

    def _link_changed(self, text: str) -> None:
        """Pasting several links at once queues them all."""
        links = find_links(text)
        if len(links) > 1:
            self.link.clear()
            self.queue_songs(links)

    def _queue_settings(self) -> tuple[str, ArrangeSettings]:
        return self.source.currentData(), self.arrange_settings()

    def _converting(self) -> bool:
        return self._job is not None and self._job.running

    def convert(self) -> None:
        typed = with_scheme(self.link.text())
        if typed and typed not in (self._link, self._downloaded):
            if not is_link(typed):
                QMessageBox.warning(self, "That isn't a link", "Paste the song's whole link, as your browser's address bar shows it.")
                return
            self.set_link(typed)
        source = str(self._path) if self._path else self._link
        if source is None:
            self.drop.choose()
            return
        self.preview.stop()
        self._job = ConvertJob(source, self.source.currentData(), self)
        self._job.progress.connect(self._on_progress)
        self._job.downloaded.connect(self._on_downloaded)
        self._job.finished.connect(self._on_converted)
        self._job.failed.connect(self._on_failed)
        self._set_busy(True)
        self.stage.setText("Starting…")
        self.progress.setValue(0)
        self._job.start()

    def cancel(self) -> None:
        if self._job and self._job.running:
            self._job.cancel()
        self._set_busy(False)
        self.stage.setText("Cancelled.")
        self.progress.setValue(0)
        self.queue.resume()

    def _set_busy(self, busy: bool) -> None:
        self.convert_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.source.setEnabled(not busy)
        self.link.setEnabled(not busy)
        self.progress.setVisible(busy)
        has_script = self._script is not None and not busy
        self.save_button.setEnabled(has_script)
        self.listen.button.setEnabled(has_script)

    def _on_progress(self, label: str, fraction: float) -> None:
        self.stage.setText(f"{label}…" if fraction < 1 else label)
        self.progress.setValue(int(fraction * 1000))

    def _on_downloaded(self, path: str, title: str) -> None:
        """The link's song is saved; converting again uses the file instead of downloading it again."""
        self._path, self._downloaded, self._link = Path(path), self._link, None
        self.drop.show_file(path)
        if not self.title.text().strip():
            self.title.setText(title)
        self.result_title.setText(self.title.text().strip())

    def _on_converted(self, song: Song) -> None:
        self._song = song
        self._set_busy(False)
        self.queue.resume()
        kind = {"midi": "MIDI file", "piano": "piano recording", "full": "full song"}.get(song.source_kind, song.source_kind)
        self.stage.setText(f"Converted as a {kind}. Change the arrangement on the left; it updates right away.")
        self._arrange()

    def _on_failed(self, message: str, details: str) -> None:
        self._set_busy(False)
        self.stage.setText("")
        self.queue.resume()
        heading = "Couldn't convert this song" if self._path else "Couldn't download this song"
        box = QMessageBox(QMessageBox.Icon.Warning, heading, message, parent=self)
        if details:
            box.setDetailedText(details)
        box.exec()

    def _arrange(self) -> None:
        if self._song is None:
            return
        try:
            script = arrange(self._song, self.arrange_settings())
        except ArrangeError as e:
            self._script = None
            self.roll.roll.clear()
            self.result_info.setText(str(e))
            self._set_busy(False)
            return
        script.meta.title = self.title.text().strip() or self._song.title
        self.preview.stop()
        self._script = script
        layout = load_layout(script.meta.layout_id)
        self.roll.roll.set_notes(script.notes, script.meta.duration, layout.low, layout.high, script.beats)
        self.result_title.setText(script.meta.title)
        self.result_info.setText(script_summary(script))
        self._set_busy(False)

    def _title_edited(self, text: str) -> None:
        if self._script is not None:
            self._script.meta.title = text.strip() or self._script.meta.title
            self.result_title.setText(self._script.meta.title)

    # ---- preview and saving

    def _listen(self) -> None:
        if self._script is not None:
            self.listen.play(self._script.notes)

    def _preview_position(self, t: float) -> None:
        if self.preview.owner is self:
            self.roll.set_position(t)

    def _preview_state(self) -> None:
        if self.listen.state is ListenState.STOPPED and self.preview.owner is self:
            self.roll.set_position(None)

    def save(self) -> None:
        if self._script is None:
            return
        title = self.title.text().strip() or self._script.meta.title or "Untitled"
        self._script.meta.title = title
        path = LIBRARY_DIR / (safe_filename(title) + EXTENSION)
        if path.exists():
            question = f"“{path.name}” is already in your library. Replace it? The old one goes to the Trash."
            if QMessageBox.question(self, "Replace script?", question) != QMessageBox.StandardButton.Yes:
                return
            if error := move_to_trash(path):
                QMessageBox.warning(self, "Couldn't replace the script", error)
                return
        try:
            write_script(self._script, path)
        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", f"The script couldn't be saved: {e.strerror}")
            return
        self.stage.setText(f"Saved “{path.name}” to your library.")
        self.saved.emit(str(path))

    def shutdown(self) -> None:
        if self._job and self._job.running:
            self._job.cancel()
        self.queue.shutdown()
