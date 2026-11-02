"""Keyboard-possible mode: no chord mixes plain keys with Shift or Ctrl ones."""

import os
import random
from collections import defaultdict

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from legatoengine import paths  # noqa: E402
from legatoengine.arrange.possible import make_possible  # noqa: E402
from legatoengine.format.apno import write_script  # noqa: E402
from legatoengine.layout import load_layout  # noqa: E402
from legatoengine.models import Modifier, Note, Role, Script, ScriptMeta  # noqa: E402
from legatoengine.player.timeline import build_timeline  # noqa: E402

M, B, H = Role.MELODY, Role.BASS, Role.HARMONY
VP61, VP88 = load_layout("vp61"), load_layout("vp88")


def chord(layout, number, start, *notes, duration=0.5):
    """notes: (pitch, role) pairs."""
    out = []
    for pitch, role in notes:
        key, modifier = layout.lookup(pitch)
        out.append(Note(pitch, start, duration, 80, role, chord=number, key=key, modifier=modifier))
    return out


def by_chord(notes):
    chords = defaultdict(list)
    for n in notes:
        chords[n.chord].append(n)
    return chords


def pitches(notes):
    return sorted(n.pitch for n in notes)


def test_a_black_key_in_a_white_chord_becomes_a_copy_of_a_chord_note():
    # D major over a D bass, the tune on D5: F#4 needs Shift, the rest don't
    notes = chord(VP61, 0, 0.0, (50, B), (66, H), (69, H), (74, M))
    out, report = make_possible(notes, VP61)
    assert pitches(out) == [50, 62, 69, 74]  # F#4 became a second D, under the tune and over the bass
    assert {n.modifier for n in out} == {Modifier.NONE}
    assert (report.chords, report.moved, report.doubled, report.dropped) == (1, 0, 1, 0)
    assert pitches(notes) == [50, 66, 69, 74]  # the script itself is left alone


def test_the_melody_decides_and_what_cant_be_copied_is_left_out():
    # an A major chord with the tune on C#5 (Shift): E4 and A4 are plain keys
    notes = chord(VP61, 0, 0.0, (64, H), (69, H), (73, M))
    out, report = make_possible(notes, VP61)
    assert pitches(out) == [61, 73]  # E4 became C#4; there's no C# left between it and the tune for A4
    assert {n.modifier for n in out} == {Modifier.SHIFT}
    assert (report.doubled, report.dropped) == (1, 1)


def test_ctrl_notes_move_an_octave_into_the_normal_keys():
    notes = chord(VP88, 0, 0.0, (21, B), (64, H), (72, M))  # A0 is Ctrl+1 in the 88-key layout
    out, report = make_possible(notes, VP88)
    bass = min(out, key=lambda n: n.pitch)
    assert (bass.pitch, bass.key, bass.modifier, bass.role) == (45, "6", Modifier.NONE, B)  # A2, still the bass
    assert report.moved == 1 and report.dropped == 0


def test_a_note_still_held_counts_as_part_of_the_harmony():
    held = chord(VP61, 0, 0.0, (49, B), duration=2.0)  # C#3, held on
    later = chord(VP61, 1, 1.0, (64, H), (70, M))  # then E4 under the tune on A#4 (Shift)
    out, report = make_possible(held + later, VP61)
    second = [n for n in out if n.chord == 1]
    assert {n.modifier for n in second} == {Modifier.SHIFT}
    assert pitches(second) == [61, 70]  # E4 became C#4, a copy of the held bass, nearer than A#3
    assert report.doubled == 1


def test_chords_that_are_already_possible_are_left_as_they_are():
    notes = chord(VP61, 0, 0.0, (48, B), (60, H), (64, H), (67, M)) + chord(VP61, 1, 0.6, (61, H), (66, H), (70, M))
    out, report = make_possible(notes, VP61)
    assert report.chords == report.changed == 0
    assert [(n.pitch, n.start, n.duration, n.key) for n in out] == [(n.pitch, n.start, n.duration, n.key) for n in notes]


@pytest.mark.parametrize("layout", [VP61, VP88], ids=lambda layout: layout.id)
def test_random_chords_always_come_out_pressable(layout):
    rng = random.Random(7)
    notes = []
    for number in range(400):
        size = rng.randint(1, 6)
        picked = rng.sample(sorted(layout.keys), size)
        picked.sort()
        roles = [H] * size
        roles[-1] = M if rng.random() < 0.8 else H
        if size > 1 and rng.random() < 0.7:
            roles[0] = B
        notes += chord(layout, number, number * 0.25, *zip(picked, roles), duration=rng.choice([0.1, 0.3, 1.5]))
    before = [(n.pitch, n.start, n.key, n.modifier) for n in notes]
    out, report = make_possible(notes, layout)
    assert [(n.pitch, n.start, n.key, n.modifier) for n in notes] == before
    assert report.chords > 100

    original = by_chord(notes)
    for number, c in by_chord(out).items():
        assert len({n.modifier for n in c}) == 1
        assert len({n.key for n in c}) == len(c)
        assert all(layout.lookup(n.pitch) == (n.key, n.modifier) for n in c)
        tune = [n.pitch for n in original[number] if n.role is M]
        if tune:  # the melody note is kept, and nothing new goes over it
            assert tune[0] in [n.pitch for n in c]
            assert sum(n.pitch > tune[0] for n in c) <= sum(n.pitch > tune[0] for n in original[number])

    # so the player presses Shift (or Ctrl) once for each chord that needs it, and never for the others
    actions = build_timeline(out)
    for modifier, name in ((Modifier.SHIFT, "shift"), (Modifier.CTRL, "ctrl")):
        needing = sum(c[0].modifier is modifier for c in by_chord(out).values())
        assert sum(a.down and a.key == name for a in actions) == needing


# ---- the Play tab


@pytest.fixture
def panel(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    QCoreApplication.setOrganizationName("LegatoEngineTest")
    QCoreApplication.setApplicationName("LegatoEngineTest")
    QApplication.instance() or QApplication([])
    from legatoengine.gui import player_panel
    from legatoengine.gui.preview import PreviewPlayer

    library = tmp_path / "library"
    monkeypatch.setattr(paths, "LIBRARY_DIR", library)
    monkeypatch.setattr(player_panel, "LIBRARY_DIR", library)
    preview = PreviewPlayer()
    heard = []
    monkeypatch.setattr(preview, "play", lambda notes, start=0.0, owner=None: heard.append(notes))
    panel = player_panel.PlayerPanel(preview)
    panel.heard = heard
    notes = chord(VP61, 0, 0.0, (50, B), (66, H), (69, H), (74, M)) + chord(VP61, 1, 1.0, (48, B), (60, H), (67, M))
    script = Script(ScriptMeta(title="Mixed chords", duration=1.5, layout_id="vp61"), notes)
    panel.path = write_script(script, library / "Mixed chords.apno")
    panel.load(panel.path)
    yield panel
    panel.shutdown()


def test_the_play_tab_toggle_changes_what_is_shown_heard_and_pressed(panel):
    from legatoengine.gui import settings

    assert not panel.possible.isChecked() and panel.possible_note.text() == ""
    assert 66 in [n.pitch for n in panel.roll.roll._notes]

    panel.possible.setChecked(True)
    assert settings.load("play/possible", False) is True
    assert panel.possible_note.text() == "1 of 2 chords changed"
    shown = panel.roll.roll._notes
    assert 66 not in [n.pitch for n in shown] and len({n.modifier for n in shown}) == 1
    panel.listen.button.click()
    assert panel.heard[-1] is panel._notes and 66 not in [n.pitch for n in panel.heard[-1]]

    panel.possible.setChecked(False)
    assert 66 in [n.pitch for n in panel.roll.roll._notes] and panel.possible_note.text() == ""

    panel.possible.setChecked(True)
    panel.load(panel.path)  # stays on for the next script
    assert panel.possible_note.text() == "1 of 2 chords changed"
