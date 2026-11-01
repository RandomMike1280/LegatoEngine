import pytest

from autopiano.arrange.chords import enforce_key_gaps, group_chords
from autopiano.arrange.cleanup import clean, drop_overtones, merge_duplicates
from autopiano.arrange.key import choose_transpose, detect_key, key_name
from autopiano.arrange.pipeline import PRESETS, ArrangeError, ArrangeSettings, arrange
from autopiano.arrange.range_fit import fit_to_range
from autopiano.arrange.reduce import ThinRules, thin_chords
from autopiano.arrange.roles import assign_skyline_roles
from autopiano.arrange.tempo import quantize_chords
from autopiano.ingest.midi import read_midi
from autopiano.layout import is_black, load_layout
from autopiano.models import Modifier, Note, Role, Song

from .helpers import scale_song, write_midi

VP61 = load_layout("vp61")


def keyed(n: Note) -> Note:
    n.key, n.modifier = VP61.lookup(n.pitch)
    return n


def song_from(tmp_path, tonic=60) -> Song:
    return read_midi(write_midi(tmp_path / f"song{tonic}.mid", scale_song(tonic)))


# ---- key and transposition


@pytest.mark.parametrize("tonic, name", [(60, "C major"), (63, "Eb major"), (67, "G major")])
def test_detects_the_key(tmp_path, tonic, name):
    song = song_from(tmp_path, tonic)
    assert key_name(*detect_key(song.notes)) == name


def test_auto_transpose_removes_black_keys(tmp_path):
    song = song_from(tmp_path, 63)  # Eb major: three flats
    assert sum(is_black(n.pitch) for n in song.notes) > 0
    shift = choose_transpose(song.notes, VP61)
    assert shift == -3  # down to C major
    assert sum(is_black(n.pitch + shift) for n in song.notes) == 0


def test_auto_transpose_leaves_c_major_alone(tmp_path):
    assert choose_transpose(song_from(tmp_path, 60).notes, VP61) == 0


# ---- cleanup


def test_merge_duplicates_and_cut_overlaps():
    notes = [Note(60, 0.0, 1.0, 50), Note(60, 0.01, 0.5, 90), Note(60, 0.5, 0.5, 70)]
    out = merge_duplicates(notes)
    assert [(n.start, n.duration, n.velocity) for n in out] == [(0.0, 0.5, 90), (0.5, 0.5, 70)]


def test_drop_overtones_keeps_real_doublings():
    loud = Note(48, 0.0, 1.0, 100)
    ghost = Note(60, 0.01, 0.9, 30)
    doubling = Note(67, 0.0, 1.0, 90)  # a twelfth above, but just as loud
    out = drop_overtones([loud, ghost, doubling])
    assert [n.pitch for n in out] == [48, 67]


def test_clean_drops_short_and_quiet_notes():
    notes = [Note(60, 0, 0.01, 80), Note(62, 0, 0.5, 5), Note(64, 0, 0.5, 80)]
    assert [n.pitch for n in clean(notes, min_duration=0.04, min_velocity=12)] == [64]


def test_full_songs_keep_short_notes_and_quiet_octaves():
    """A separated stem's decays are cut short and its quiet octaves are mostly real; a piano recording's aren't."""
    tune, bass = Note(72, 0.0, 0.5, 90, Role.MELODY), Note(36, 3.0, 0.5, 90, Role.BASS)
    loud, octave = Note(48, 1.0, 1.0, 100), Note(60, 1.0, 1.0, 40)
    cut_short = Note(67, 2.0, 0.035, 80)
    for kind, kept in (("full", True), ("piano", False)):
        song = Song(notes=[tune, loud, octave, cut_short, bass], duration=4.0, source_kind=kind)
        played = {n.pitch for n in arrange(song, ArrangeSettings(transpose="original")).notes}
        assert (octave.pitch in played, cut_short.pitch in played) == (kept, kept)


# ---- roles


def test_skyline_finds_melody_and_bass():
    notes = [
        Note(76, 0.0, 1.0), Note(60, 0.0, 1.0), Note(40, 0.0, 1.0),
        Note(64, 0.5, 0.5),  # struck under the still-ringing melody note: accompaniment
        Note(79, 1.0, 1.0), Note(43, 1.0, 1.0),
    ]  # fmt: skip
    assign_skyline_roles(notes)
    roles = {(n.pitch, n.start): n.role for n in notes}
    assert roles[(76, 0.0)] is Role.MELODY
    assert roles[(79, 1.0)] is Role.MELODY
    assert roles[(64, 0.5)] is Role.HARMONY
    assert roles[(40, 0.0)] is Role.BASS
    assert roles[(43, 1.0)] is Role.BASS
    assert roles[(60, 0.0)] is Role.HARMONY


# ---- range and chords


def test_fit_to_range_folds_by_octaves():
    notes = [Note(p, i * 0.1, 0.1) for i, p in enumerate([20, 30, 60, 100, 110, 127])]
    out = fit_to_range(notes, 36, 96)
    assert all(36 <= n.pitch <= 96 for n in out)
    assert [n.pitch % 12 for n in out] == [p % 12 for p in [20, 30, 60, 100, 110, 127]]


def test_fit_to_range_moves_vocal_melody_above_the_chords():
    notes = [Note(p, i * 0.5, 0.5, role=Role.MELODY) for i, p in enumerate([50, 52, 53, 55])]
    notes += [Note(30, 0, 2, role=Role.BASS)]
    out = fit_to_range(notes, 36, 96, move_lines=True)
    melody = [n.pitch for n in out if n.role is Role.MELODY]
    assert melody == [74, 76, 77, 79]
    assert [n.pitch for n in out if n.role is Role.BASS] == [42]


def test_group_chords_aligns_starts():
    notes = [Note(60, 0.0, 1.0), Note(64, 0.01, 0.99), Note(67, 0.02, 0.98), Note(72, 0.5, 0.5)]
    chords = group_chords(notes, 0.025)
    assert [[n.pitch for n in c] for c in chords] == [[60, 64, 67], [72]]
    assert all(n.start == 0.0 and n.end == pytest.approx(1.0) for n in chords[0])


def test_quantize_snaps_toward_the_grid():
    chords = [[Note(60, 0.27, 0.2)], [Note(62, 0.49, 0.2)]]
    quantize_chords(chords, beats=[0.0, 1.0, 2.0], strength=1.0, subdivision=4)
    assert [c[0].start for c in chords] == [0.25, 0.5]


def test_enforce_key_gaps_trims_and_drops():
    a = keyed(Note(60, 0.0, 1.0, role=Role.HARMONY))  # T
    b = keyed(Note(61, 0.5, 0.2, role=Role.MELODY))  # Shift+T
    out = enforce_key_gaps([a, b])
    assert len(out) == 2
    assert out[0].end == pytest.approx(0.48)
    c = keyed(Note(60, 0.0, 1.0, role=Role.HARMONY))
    d = keyed(Note(61, 0.01, 1.0, role=Role.MELODY))
    assert [n.pitch for n in enforce_key_gaps([c, d])] == [61]  # too close: the melody note wins


def test_thin_chords_keeps_melody_and_bass_first():
    chord = [keyed(Note(p, 0, 1, 80, Role.HARMONY)) for p in (48, 52, 55, 60, 64, 67)]
    chord.append(keyed(Note(76, 0, 1, 90, Role.MELODY)))
    chord.append(keyed(Note(36, 0, 1, 90, Role.BASS)))
    out = thin_chords([chord], VP61, ThinRules(max_keys=3))
    pitches = sorted(n.pitch for n in out[0])
    assert 76 in pitches and 36 in pitches and len(pitches) == 3


def test_thin_chords_prefers_new_pitch_classes_over_octaves():
    chord = [keyed(Note(76, 0, 1, 90, Role.MELODY))]
    chord += [keyed(Note(64, 0, 1, 100, Role.HARMONY)), keyed(Note(67, 0, 1, 60, Role.HARMONY))]
    out = thin_chords([chord], VP61, ThinRules(max_keys=2))
    assert sorted(n.pitch for n in out[0]) == [67, 76]  # 64 is another E, like the melody


def test_melody_on_top_moves_harmony_under_the_tune():
    melody = keyed(Note(72, 0, 2, 90, Role.MELODY))
    high = keyed(Note(76, 0.5, 0.5, 80, Role.HARMONY))
    out = thin_chords([[melody], [high]], VP61, ThinRules(melody_on_top=True))
    moved = out[1][0]
    assert moved.pitch == 64
    assert (moved.key, moved.modifier) == VP61.lookup(64)


# ---- whole pipeline


def check_script(script, max_keys):
    layout = load_layout(script.meta.layout_id)
    by_chord = {}
    for n in script.notes:
        assert layout.lookup(n.pitch) == (n.key, n.modifier)
        by_chord.setdefault(n.chord, []).append(n)
    chord_ids = [n.chord for n in script.notes]
    assert chord_ids == sorted(chord_ids)
    for chord in by_chord.values():
        assert len(chord) <= max_keys
        assert len({n.key for n in chord}) == len(chord)  # one note per physical key
        assert len({n.start for n in chord}) == 1


@pytest.mark.parametrize("preset", list(PRESETS))
def test_every_preset_makes_a_valid_script(tmp_path, preset):
    script = arrange(song_from(tmp_path, 63), ArrangeSettings(preset=preset))
    check_script(script, PRESETS[preset].max_keys)
    assert script.meta.key_name == "Eb major"
    assert script.meta.transpose == -3
    if preset == "melody":
        assert {n.role for n in script.notes} == {Role.MELODY}
        assert len(script.notes) == 16


def test_presets_get_lighter(tmp_path):
    song = song_from(tmp_path)
    counts = [len(arrange(song, ArrangeSettings(preset=p)).notes) for p in ("full", "simplified", "melody_bass", "melody")]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]


def test_original_key_and_manual_transpose(tmp_path):
    song = song_from(tmp_path, 63)
    assert arrange(song, ArrangeSettings(transpose="original")).meta.transpose == 0
    script = arrange(song, ArrangeSettings(transpose=2))
    assert script.meta.transpose == 2
    assert any(n.modifier is Modifier.SHIFT for n in script.notes)


def test_88_key_layout_keeps_low_notes(tmp_path):
    notes = [Note(24, 0, 1, 90, Role.BASS), Note(72, 0, 1, 90, Role.MELODY)]
    song = Song(notes=notes, duration=1, source_kind="midi")
    s61 = arrange(song, ArrangeSettings(layout_id="vp61", transpose="original"))
    s88 = arrange(song, ArrangeSettings(layout_id="vp88", transpose="original"))
    assert min(n.pitch for n in s61.notes) == 36
    low = min(s88.notes, key=lambda n: n.pitch)
    assert (low.pitch, low.modifier) == (24, Modifier.CTRL)


def test_empty_song_is_an_error():
    with pytest.raises(ArrangeError):
        arrange(Song(notes=[], duration=0, source_kind="midi"))
