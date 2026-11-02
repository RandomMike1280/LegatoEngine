"""The felt piano that ▶ Listen plays, and the player that makes its audio in the background."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import sounddevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from legatoengine.gui import preview as preview_module  # noqa: E402
from legatoengine.gui.preview import ListenControls, ListenState, PreviewPlayer, SpaceListens  # noqa: E402
from legatoengine.models import Note  # noqa: E402
from legatoengine.synth import SAMPLE_RATE, render_felt  # noqa: E402

SR = SAMPLE_RATE


def _band(audio: np.ndarray, low: float, high: float) -> float:
    spectrum = np.abs(np.fft.rfft(audio.mean(axis=1))) ** 2
    freqs = np.fft.rfftfreq(len(audio), 1 / SR)
    return float(spectrum[(freqs >= low) & (freqs < high)].sum())


def test_felt_piano_is_in_tune_soft_on_top_and_stereo():
    audio = render_felt([Note(69, 0.1, 2.0, 90)])
    assert audio.dtype == np.float32 and audio.ndim == 2 and audio.shape[1] == 2
    assert np.isfinite(audio).all() and np.abs(audio).max() <= 1.0
    assert len(audio) / SR > 2.0 + 1.0  # the room rings on after the note

    held = audio[int(0.2 * SR) : int(1.6 * SR)].mean(axis=1)
    spectrum = np.abs(np.fft.rfft(held * np.hanning(len(held)), 16 * len(held)))
    peak = np.fft.rfftfreq(16 * len(held), 1 / SR)[spectrum.argmax()]
    assert abs(1200 * np.log2(peak / 440)) < 12  # the tape wobble bends it by a few cents, no more

    assert _band(audio, 5500, 11000) < 0.002 * _band(audio, 200, 2000)  # the lofi top end is rolled off


def test_harder_notes_are_brighter_and_low_notes_sit_left():
    soft = render_felt([Note(60, 0, 1.0, 30)])
    hard = render_felt([Note(60, 0, 1.0, 120)])
    assert np.abs(hard).max() > np.abs(soft).max() * 0.9  # both are brought to the same peak level
    brightness = [_band(a, 1500, 5000) / _band(a, 200, 600) for a in (soft, hard)]
    assert brightness[1] > 3 * brightness[0]

    low = render_felt([Note(40, 0, 1.0, 90)])[: SR]
    high = render_felt([Note(88, 0, 1.0, 90)])[: SR]
    assert (low[:, 0] ** 2).sum() > (low[:, 1] ** 2).sum()
    assert (high[:, 1] ** 2).sum() > (high[:, 0] ** 2).sum()


def test_hiss_is_faint_and_silence_stays_quiet():
    audio = render_felt([Note(60, 2.0, 0.5, 90)])
    before = audio[: int(1.9 * SR)]
    rms = float(np.sqrt((before.astype(np.float64) ** 2).mean()))
    assert 0.001 < rms < 0.01  # about -45 dB: there, but well under the music
    assert render_felt([]).shape == (0, 2)


def test_sustain_lets_notes_ring_on_until_their_key_is_struck_again():
    short = [Note(60, 0.1, 0.2, 90)]
    dry, wet = render_felt(short), render_felt(short, sustain=True)
    assert len(wet) > len(dry) + SR  # it rings for seconds, not a fifth of one

    def level(audio, a, b):
        return float(np.sqrt((audio[int(a * SR) : int(b * SR)].astype(np.float64) ** 2).mean()))

    assert level(wet, 0.8, 1.6) > 10 * level(dry, 0.8, 1.6)  # long after the key was let go
    assert level(wet, 0.12, 0.28) == pytest.approx(level(dry, 0.12, 0.28), rel=0.2)  # held, it's the same note

    from legatoengine.synth import FELT_RING, _with_pedal

    notes = [Note(60, 0.0, 0.1, 90), Note(64, 0.5, 0.1, 90), Note(60, 1.0, 0.1, 90), Note(60, 1.0, 0.1, 70)]
    # struck again, the string that was ringing stops; the others ring as long as a felt piano can
    assert _with_pedal(notes) == [1.0, FELT_RING, 0.0, FELT_RING]


@pytest.fixture
def speaker(monkeypatch):
    """Stands in for the sound card."""
    played = []
    monkeypatch.setattr(sounddevice, "play", lambda audio, rate: played.append((audio, rate)))
    monkeypatch.setattr(sounddevice, "stop", lambda: None)
    QApplication.instance() or QApplication([])
    return played


def _wait(until, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        QApplication.processEvents()
        time.sleep(0.01)


def test_player_makes_the_audio_in_the_background(speaker):
    player = PreviewPlayer()
    states = []
    player.state_changed.connect(lambda: states.append(player.state))
    notes = [Note(60 + i, i * 0.3, 0.3, 90) for i in range(12)]

    assert player.play(notes, start=1.0, owner="me") is None
    assert player.state is ListenState.LOADING and speaker == []  # getting ready: the button already offers Pause
    _wait(lambda: speaker)
    audio, rate = speaker[0]
    assert rate == SR and audio.shape[1] == 2
    assert len(audio) == len(render_felt(notes)) - SR  # started one second in
    assert states == [ListenState.LOADING, ListenState.PLAYING]

    player.stop()
    assert player.state is ListenState.STOPPED
    assert player.play(notes, owner="me") is None and len(speaker) == 2  # heard last, so it starts at once
    player.stop()

    other = [Note(72, 0, 1.0, 90)]
    player.play(other, owner="me")
    player.stop()  # stopped before its audio was ready: it never plays
    _wait(lambda: not player._rendering)
    QApplication.processEvents()
    assert len(speaker) == 2 and player.state is ListenState.STOPPED


def test_pause_and_continue_pick_up_where_it_was(speaker):
    player = PreviewPlayer()
    notes = [Note(60 + i, i * 0.3, 0.3, 90) for i in range(12)]
    player.play(notes, owner="me")
    _wait(lambda: speaker)
    full = len(speaker[0][0])
    time.sleep(0.3)
    player.pause()
    paused_at = player.position
    assert player.state is ListenState.PAUSED and 0.25 < paused_at < 0.6
    time.sleep(0.2)
    assert player.position == paused_at  # paused time doesn't count

    assert player.resume() is None and player.state is ListenState.PLAYING
    assert len(speaker[1][0]) == full - int(paused_at * SR)  # carries on from the same sample
    assert player.position == pytest.approx(paused_at, abs=0.02)
    player.stop()
    assert player.state is ListenState.STOPPED and player.resume() is None  # nothing to carry on

    # paused before its audio was ready: it waits, and plays only when told
    later = [Note(70, 0, 1.0, 90)]
    player.play(later, start=0.5, owner="me")
    player.pause()
    _wait(lambda: not player._rendering)
    QApplication.processEvents()
    assert len(speaker) == 2 and player.state is ListenState.PAUSED
    player.resume()
    assert len(speaker) == 3 and len(speaker[2][0]) == len(render_felt(later)) - SR // 2


def test_sustain_takes_over_where_the_music_was(speaker):
    player = PreviewPlayer()
    changes = []
    player.sustain_changed.connect(changes.append)
    notes = [Note(60 + i, i * 0.3, 0.1, 90) for i in range(12)]
    player.play(notes, owner="me")
    _wait(lambda: speaker)
    time.sleep(0.3)

    player.set_sustain(True)
    assert changes == [True] and player.sustain
    assert player.state is ListenState.LOADING  # the sustained version is being made
    _wait(lambda: len(speaker) == 2)
    wet = render_felt(notes, sustain=True)
    resumed_at = len(wet) - len(speaker[1][0])
    assert 0.25 * SR < resumed_at < 0.6 * SR and player.state is ListenState.PLAYING

    player.set_sustain(False)  # made before, so it's back at once
    assert len(speaker) == 3 and player.state is ListenState.PLAYING
    player.set_sustain(False)
    assert changes == [True, False]

    player.pause()
    player.set_sustain(True)  # paused, it waits for Continue, which plays it with sustain
    assert player.state is ListenState.PAUSED and len(speaker) == 3
    player.resume()
    assert len(speaker) == 4 and len(speaker[3][0]) > len(wet) - SR  # the kept sustained version
    player.stop()


def test_player_reports_errors_that_come_later(speaker, monkeypatch):
    player = PreviewPlayer()
    failures = []
    player.failed.connect(failures.append)

    def no_device(audio, rate):
        raise RuntimeError("no output device")

    monkeypatch.setattr(sounddevice, "play", no_device)
    player.play([Note(60, 0, 0.5, 90)], owner="me")
    _wait(lambda: failures)
    assert failures == ["Couldn't play audio: no output device"] and player.state is ListenState.STOPPED

    monkeypatch.setattr(preview_module, "render_felt", lambda notes, rate, sustain: 1 / 0)
    player.play([Note(62, 0, 0.5, 90)], owner="me")
    _wait(lambda: len(failures) == 2)
    assert failures[1].startswith("Couldn't make the preview") and player.state is ListenState.STOPPED


# ---- the controls each tab shows, and Space


class Tab(QWidget):
    """A tab with its own notes and Listen controls, like the Convert, Play and Edit tabs."""

    def __init__(self, preview, notes):
        super().__init__()
        self.notes = notes
        self.listen = ListenControls(preview, self, lambda: self.listen.play(self.notes))


def test_each_tab_shows_its_own_listening_and_sustain_is_shared(speaker):
    preview = PreviewPlayer()
    notes = [Note(60, 0, 0.5, 90)]
    one, two = Tab(preview, notes), Tab(preview, [Note(64, 0, 0.5, 90)])
    button, stop = one.listen.button, one.listen.stop_button
    assert button.text() == "▶ Listen" and stop.isHidden()

    button.click()
    assert button.text() == "❚❚ Pause" and not stop.isHidden()  # pausable while it's being made
    _wait(lambda: preview.state is ListenState.PLAYING)
    button.click()
    assert button.text() == "▶ Continue" and preview.state is ListenState.PAUSED
    button.click()
    assert button.text() == "❚❚ Pause" and preview.state is ListenState.PLAYING
    assert two.listen.button.text() == "▶ Listen" and two.listen.state is ListenState.STOPPED

    two.listen.button.click()  # the other tab takes over
    assert button.text() == "▶ Listen" and stop.isHidden() and preview.owner is two
    two.listen.stop_button.click()
    assert two.listen.button.text() == "▶ Listen" and preview.state is ListenState.STOPPED

    one.listen.sustain.setChecked(True)
    assert preview.sustain and two.listen.sustain.isChecked()
    preview.set_sustain(False)
    assert not one.listen.sustain.isChecked() and not two.listen.sustain.isChecked()

    button.setEnabled(False)
    one.listen.toggle()  # nothing to listen to
    assert preview.state is ListenState.STOPPED


def test_space_pauses_and_continues_but_never_presses_a_button_or_eats_typing(speaker):
    preview = PreviewPlayer()
    window = QWidget()
    tab = Tab(preview, [Note(60, 0, 2.0, 90)])
    play, typed = QPushButton("▶ Play"), QLineEdit()
    pressed = []
    play.clicked.connect(lambda: pressed.append(True))
    layout = QVBoxLayout(window)
    for w in (tab, play, typed):
        layout.addWidget(w)
    SpaceListens(window, preview, lambda: tab.listen)
    window.show()
    window.activateWindow()
    play.setFocus()
    QApplication.processEvents()

    QTest.keyClick(play, Qt.Key.Key_Space)
    assert preview.state is ListenState.LOADING and pressed == []  # it listens; ▶ Play isn't pressed
    _wait(lambda: preview.state is ListenState.PLAYING)
    QTest.keyClick(play, Qt.Key.Key_Space)
    assert preview.state is ListenState.PAUSED and tab.listen.button.text() == "▶ Continue"
    QTest.keyPress(play, Qt.Key.Key_Space)
    QTest.keyRelease(play, Qt.Key.Key_Space)
    assert preview.state is ListenState.PLAYING and pressed == []

    typed.setFocus()
    QApplication.processEvents()
    QTest.keyClicks(typed, "fur elise")
    assert typed.text() == "fur elise" and preview.state is ListenState.PLAYING  # typing a space is just a space

    play.setFocus()
    QApplication.processEvents()
    QTest.keyClick(play, Qt.Key.Key_Space, Qt.KeyboardModifier.ShiftModifier)  # not plain Space
    assert preview.state is ListenState.PLAYING
    preview.stop()
    window.close()
