import pytest

from autopiano.format.apno import ApnoError, dumps, loads, read_script, script_to_payload, seal, write_script
from autopiano.models import Modifier, Note, Role, Script, ScriptMeta


def make_script() -> Script:
    notes = [
        Note(60, 0.0, 0.5, 90, Role.MELODY, chord=0, key="t", modifier=Modifier.NONE),
        Note(64, 0.0, 0.5, 70, Role.HARMONY, chord=0, key="u", modifier=Modifier.NONE),
        Note(61, 0.5, 0.25, 70, Role.HARMONY, chord=1, key="t", modifier=Modifier.SHIFT),
        Note(21, 1.0, 1.0, 64, Role.BASS, chord=2, key="1", modifier=Modifier.CTRL),
    ]
    meta = ScriptMeta(
        title="Test Song",
        source_name="test.mid",
        source_hash="abc123",
        source_kind="midi",
        duration=2.0,
        bpm=120.0,
        key_name="C major",
        transpose=-3,
        layout_id="vp88",
        preset="full",
        settings={"max_chord": 8, "quantize": 0.0},
        converter_version="0.1.0",
        created=1700000000.0,
    )
    return Script(meta, notes, beats=[0.0, 0.5, 1.0, 1.5], pedals=[(0.0, 1.25)])


def test_round_trip(tmp_path):
    script = make_script()
    path = write_script(script, tmp_path / "song")
    assert path.suffix == ".apno"
    back = read_script(path)
    assert back.meta == script.meta
    assert back.notes == script.notes
    assert back.beats == script.beats
    assert back.pedals == script.pedals


def test_contents_are_not_readable():
    data = dumps(make_script())
    assert data[:4] == b"APNO"
    assert b"Test Song" not in data
    assert b"C major" not in data


def test_any_changed_byte_is_rejected():
    data = dumps(make_script())
    for i in range(len(data)):
        damaged = bytearray(data)
        damaged[i] ^= 0x01
        with pytest.raises(ApnoError):
            loads(bytes(damaged))


def test_truncated_file_is_rejected():
    data = dumps(make_script())
    with pytest.raises(ApnoError):
        loads(data[:-1])


def test_other_files_are_rejected():
    with pytest.raises(ApnoError, match="not an AutoPiano script"):
        loads(b"MThd\x00\x00\x00\x06")


def test_newer_format_is_rejected():
    data = seal(script_to_payload(make_script()), version=2)
    with pytest.raises(ApnoError, match="newer"):
        loads(data)


def test_every_note_needs_a_key():
    script = make_script()
    script.notes[0].key = ""
    with pytest.raises(ValueError):
        dumps(script)
