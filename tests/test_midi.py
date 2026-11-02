import pytest

from legatoengine.ingest.midi import TempoMap, read_midi
from legatoengine.models import Role

from .helpers import TPB, scale_song, write_midi


def test_reads_notes_roles_timing_and_pedal(tmp_path):
    path = write_midi(
        tmp_path / "song.mid",
        [
            {"name": "Lead Vocals", "notes": [(72, 0, 1, 100), (74, 1, 1, 100)]},
            {"name": "Piano", "program": 0, "notes": [(60, 0, 2, 70), (64, 0, 2, 70)], "pedal": [(0, 2)]},
            {"name": "Synth", "program": 38, "channel": 1, "notes": [(36, 0, 2, 90)]},
            {"name": "Drums", "channel": 9, "notes": [(36, 0, 0.25, 100)]},
        ],
        bpm=100,
    )
    song = read_midi(path)
    assert song.source_kind == "midi"
    assert song.title == "song"
    assert len(song.notes) == 5  # drums skipped
    roles = {n.pitch: n.role for n in song.notes}
    assert roles == {72: Role.MELODY, 74: Role.MELODY, 60: Role.HARMONY, 64: Role.HARMONY, 36: Role.BASS}
    second = next(n for n in song.notes if n.pitch == 74)
    assert second.start == pytest.approx(0.6)  # one beat at 100 BPM
    assert second.duration == pytest.approx(0.6)
    assert song.tempo == pytest.approx(100)
    assert song.beats[:3] == pytest.approx([0.0, 0.6, 1.2])
    assert song.pedals == [pytest.approx((0.0, 1.2))]
    assert song.duration == pytest.approx(1.2)


def test_tempo_changes():
    tempo = TempoMap(TPB, [(0, 500_000), (TPB * 4, 1_000_000)])  # 120 BPM, then 60 BPM after 4 beats
    assert tempo.seconds(TPB * 4) == pytest.approx(2.0)
    assert tempo.seconds(TPB * 5) == pytest.approx(3.0)


def test_guesses_the_melody_track_when_none_is_named(tmp_path):
    line = [(70 + (i % 5), i * 0.5, 0.5, 90) for i in range(32)]
    pad = [(p, bar * 4, 4, 60) for bar in range(4) for p in (48, 55, 60, 64)]
    path = write_midi(tmp_path / "x.mid", [{"name": "Track 1", "notes": pad}, {"name": "Track 2", "notes": line}])
    song = read_midi(path)
    assert {n.role for n in song.notes if n.pitch >= 70} == {Role.MELODY}
    assert {n.role for n in song.notes if n.pitch < 70} == {Role.HARMONY}


def test_empty_midi_is_an_error(tmp_path):
    path = write_midi(tmp_path / "drums.mid", [{"name": "Drums", "channel": 9, "notes": [(36, 0, 1, 100)]}])
    with pytest.raises(ValueError):
        read_midi(path)


def test_scale_song_helper_round_trips(tmp_path):
    song = read_midi(write_midi(tmp_path / "s.mid", scale_song()))
    assert len(song.notes) == 16 + 12 + 4
