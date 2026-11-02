import pytest

from legatoengine.arrange.edit import EditError, Edits, clock, edit_script
from legatoengine.arrange.pipeline import ArrangeSettings, arrange
from legatoengine.format.apno import read_script, write_script
from legatoengine.layout import load_layout
from legatoengine.models import Modifier, Note, Role, Song
from legatoengine.player.timeline import build_timeline, simulate_typing

from .test_arrange import check_script, song_from

VP61 = load_layout("vp61")


def script_of(tmp_path, tonic=60):
    """I-IV-V-I in C over 4 s: a melody note every 0.25 s, chords and bass held for each 1 s bar."""
    return arrange(song_from(tmp_path, tonic), ArrangeSettings(transpose="original"))


def notes_script(notes, layout_id="vp61"):
    return arrange(Song(notes=notes, duration=max(n.end for n in notes), source_kind="midi"),
                   ArrangeSettings(transpose="original", layout_id=layout_id))


def summary(script):
    return [(n.pitch, n.start, n.duration, n.key, n.modifier, n.chord) for n in script.notes]


def test_no_edits_keep_the_script(tmp_path):
    script = script_of(tmp_path)
    edited = edit_script(script, Edits())
    assert summary(edited) == summary(script)
    assert edited.meta.duration == script.meta.duration
    assert edited.beats == script.beats


def test_trim_keeps_the_middle_and_starts_it_at_zero(tmp_path):
    script = script_of(tmp_path)
    edited = edit_script(script, Edits(start=1.0, end=3.0))
    melody = [n for n in edited.notes if n.role is Role.MELODY]
    assert [n.start for n in melody] == pytest.approx([0.25 * i for i in range(8)])
    assert sorted({n.start for n in edited.notes if n.role is not Role.MELODY}) == [0.0, 1.0]  # two bars
    assert max(n.end for n in edited.notes) <= 2.0
    assert edited.meta.duration == pytest.approx(2.0)
    assert edited.beats == pytest.approx([0.0, 0.5, 1.0, 1.5])
    check_script(edited, 8)


def test_trim_cuts_notes_held_past_the_end(tmp_path):
    edited = edit_script(script_of(tmp_path), Edits(end=1.5))  # halfway through the second bar
    assert max(n.end for n in edited.notes) == pytest.approx(1.5)
    assert sorted(round(n.duration, 3) for n in edited.notes if n.role is Role.BASS) == [0.5, 1.0]


def test_tempo_scales_every_time(tmp_path):
    script = script_of(tmp_path)
    edited = edit_script(script, Edits(tempo=2.0))
    assert [n.start for n in edited.notes] == pytest.approx([n.start / 2 for n in script.notes], abs=0.001)
    # within the 20 ms a key needs between presses, which a faster tempo doesn't shrink
    assert [n.duration for n in edited.notes] == pytest.approx([n.duration / 2 for n in script.notes], abs=0.0101)
    assert edited.meta.duration == pytest.approx(script.meta.duration / 2)
    assert edited.meta.bpm == pytest.approx(script.meta.bpm * 2, abs=0.1)
    slower = edit_script(script, Edits(tempo=0.5))
    assert slower.meta.duration == pytest.approx(script.meta.duration * 2)


def test_faster_tempo_keeps_a_gap_before_a_key_is_pressed_again():
    repeats = [Note(72, 0.1 * i, 0.1, 90, Role.MELODY) for i in range(10)]
    edited = edit_script(notes_script(repeats), Edits(tempo=4.0))  # 25 ms apart
    for a, b in zip(edited.notes, edited.notes[1:]):
        assert b.start - a.end >= 0.02 - 1e-9


def test_transpose_moves_every_note_and_its_key(tmp_path):
    script = script_of(tmp_path)
    up = edit_script(script, Edits(transpose=12))
    assert sorted(n.pitch for n in up.notes) == sorted(n.pitch + 12 for n in script.notes)
    assert summary(edit_script(up, Edits(transpose=-12))) == summary(script)
    edited = edit_script(script, Edits(transpose=3))  # C major moved to Eb major
    assert edited.meta.transpose == script.meta.transpose + 3
    assert any(n.modifier is Modifier.SHIFT for n in edited.notes)
    check_script(edited, 8)
    # D5 under the melody's Eb5 would share its key; only those chord notes are dropped
    dropped = sorted(n.pitch + 3 for n in script.notes)
    for n in edited.notes:
        dropped.remove(n.pitch)
    assert dropped and set(dropped) == {74}


def test_transpose_folds_notes_back_into_range():
    edited = edit_script(notes_script([Note(95, 0, 1, 90, Role.MELODY), Note(37, 0, 1, 90, Role.BASS)]), Edits(transpose=4))
    assert sorted(n.pitch for n in edited.notes) == [41, 99 - 12]
    edited = edit_script(notes_script([Note(37, 0, 1, 90, Role.BASS)]), Edits(transpose=-4))
    assert [n.pitch for n in edited.notes] == [33 + 12]


def test_transpose_keeps_one_note_per_physical_key():
    assert VP61.lookup(60)[0] == VP61.lookup(61)[0]  # C4 and C#4 are the same key, with and without Shift
    chord = [Note(59, 0, 1, 70, Role.HARMONY), Note(60, 0, 1, 90, Role.MELODY), Note(64, 0, 1, 70, Role.HARMONY)]
    edited = edit_script(notes_script(chord), Edits(transpose=1))  # 60 and 61 now share a key
    assert sorted(n.pitch for n in edited.notes) == [61, 65]
    assert next(n for n in edited.notes if n.pitch == 61).role is Role.MELODY


def test_leave_out_parts_and_press_fewer_keys(tmp_path):
    script = script_of(tmp_path)
    tune_and_bass = edit_script(script, Edits(parts=frozenset({Role.MELODY, Role.BASS})))
    assert {n.role for n in tune_and_bass.notes} == {Role.MELODY, Role.BASS}
    two = edit_script(script, Edits(max_keys=2))
    check_script(two, 2)
    assert [n for n in two.notes if n.role is Role.MELODY] == [n for n in script.notes if n.role is Role.MELODY]
    with pytest.raises(EditError):
        edit_script(script, Edits(parts=frozenset()))


def test_move_to_the_other_piano():
    script = notes_script([Note(24, 0, 1, 90, Role.BASS), Note(72, 0, 1, 90, Role.MELODY)], "vp88")
    assert min(script.notes, key=lambda n: n.pitch).modifier is Modifier.CTRL
    edited = edit_script(script, Edits(layout_id="vp61"))
    assert edited.meta.layout_id == "vp61"
    assert sorted(n.pitch for n in edited.notes) == [36, 72]
    assert all(n.modifier is not Modifier.CTRL for n in edited.notes)
    check_script(edited, 8)


def test_impossible_edits_are_errors(tmp_path):
    script = script_of(tmp_path)
    for edits in (Edits(start=5, end=5), Edits(start=20), Edits(tempo=10), Edits(tempo=0)):
        with pytest.raises(EditError):
            edit_script(script, edits)


def test_edited_scripts_save_play_and_remember_their_edits(tmp_path):
    script = script_of(tmp_path)
    once = edit_script(script, Edits(start=1, end=3, transpose=2, tempo=1.1, title="Middle"))
    twice = edit_script(once, Edits(parts=frozenset({Role.MELODY})))
    path = write_script(twice, tmp_path / "middle.apno")
    loaded = read_script(path)
    assert summary(loaded) == summary(twice)
    assert loaded.meta.title == "Middle"
    history = [Edits.from_dict(d).describe() for d in loaded.meta.settings["edits"]]
    assert history == ["trimmed to 0:01–0:03, up 2 semitones, 110% tempo", "without bass and chords"]
    assert simulate_typing(build_timeline(loaded.notes)) != ""


def test_clock():
    assert [clock(t) for t in (0, 5, 65, 65.34, 599.96)] == ["0:00", "0:05", "1:05", "1:05.3", "10:00"]
