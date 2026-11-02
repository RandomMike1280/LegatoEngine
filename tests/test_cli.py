from collections import defaultdict

import pytest

from legatoengine import cli
from legatoengine.format.apno import read_script
from legatoengine.models import Modifier
from legatoengine.player.timeline import build_timeline, simulate_typing

from .helpers import write_midi


def _song(tmp_path):
    notes = [(60 + p, i * 0.5, 0.5, 90) for i, p in enumerate([0, 2, 4, 5, 7, 9, 11, 12])]
    return write_midi(tmp_path / "scale.mid", [{"name": "Piano", "program": 0, "notes": notes}])


def test_convert_then_info(tmp_path, capsys):
    out = tmp_path / "scripts"
    out.mkdir()
    assert cli.main(["convert", str(_song(tmp_path)), "-o", str(out), "--style", "melody", "--title", "Test Song"]) == 0
    path = out / "Test Song.apno"
    script = read_script(path)
    assert script.meta.title == "Test Song"
    assert script.meta.preset == "melody"
    assert len(script.notes) == 8

    capsys.readouterr()
    assert cli.main(["info", str(path)]) == 0
    text = capsys.readouterr().out
    assert "Test Song" in text and "Melody only" in text and "8 notes" in text


def test_output_ending_in_a_slash_is_a_new_folder(tmp_path):
    folder = tmp_path / "Covers"
    for title in ("One", "Two"):
        assert cli.main(["convert", str(_song(tmp_path)), "-o", f"{folder}/", "--title", title]) == 0
    assert sorted(p.name for p in folder.iterdir()) == ["One.apno", "Two.apno"]
    assert cli.main(["edit", str(folder / "One.apno"), "--tempo", "120", "-o", f"{tmp_path}/Edited/"]) == 0
    assert [p.name for p in (tmp_path / "Edited").iterdir()] == ["One (edited).apno"]


def test_convert_options_reach_the_arranger(tmp_path):
    path = tmp_path / "up.apno"
    assert cli.main(["convert", str(_song(tmp_path)), "-o", str(path), "--key", "2", "--piano", "vp88"]) == 0
    meta = read_script(path).meta
    assert meta.transpose == 2
    assert meta.layout_id == "vp88"


def test_bad_input_is_reported_not_raised(tmp_path, capsys):
    assert cli.main(["convert", str(tmp_path / "missing.mp3")]) == 1
    assert cli.main(["convert", str(_song(tmp_path)), "--key", "higher"]) == 1
    junk = tmp_path / "junk.apno"
    junk.write_bytes(b"not a script")
    assert cli.main(["info", str(junk)]) == 1
    assert "legatoengine-cli:" in capsys.readouterr().err


def test_conversions_restart_to_free_memory_at_once(monkeypatch):
    restarts = []

    def execv(path, args):
        restarts.append(args)
        raise SystemExit(0)

    monkeypatch.delenv("MallocLargeCache", raising=False)
    monkeypatch.setattr(cli.os, "execv", execv)
    monkeypatch.setattr(cli, "main", lambda: 0)
    monkeypatch.setattr(cli, "move_old_folders", lambda: [])
    monkeypatch.setattr(cli.sys, "argv", ["legatoengine-cli", "info", "s.apno"])
    assert cli.run() == 0 and not restarts
    monkeypatch.setattr(cli.sys, "argv", ["legatoengine-cli", "convert", "song.mp3"])
    monkeypatch.setattr(cli.sys, "orig_argv", ["python", "/venv/bin/legatoengine-cli", "convert", "song.mp3"])
    with pytest.raises(SystemExit):
        cli.run()
    assert restarts == [[cli.sys.executable, "/venv/bin/legatoengine-cli", "convert", "song.mp3"]]
    assert cli.os.environ["MallocLargeCache"] == "0"
    assert cli.run() == 0 and len(restarts) == 1  # the restarted process just converts


def test_dry_run_presses_every_note(tmp_path, capsys):
    path = tmp_path / "s.apno"
    assert cli.main(["convert", str(_song(tmp_path)), "-o", str(path)]) == 0
    capsys.readouterr()
    assert cli.main(["play", str(path), "--dry-run", "--speed", "4"]) == 0
    lines = capsys.readouterr().out.splitlines()
    downs = [line.split()[-1] for line in lines if " down " in line]
    assert len(downs) == len(read_script(path).notes)


def test_keytest_passage():
    notes = cli.keytest_notes()
    assert all(n.modifier is not Modifier.CTRL for n in notes)  # Ctrl+letter edits text instead of typing
    keys_per_chord = defaultdict(list)
    for n in notes:
        keys_per_chord[n.chord].append(n.key)
    assert all(len(keys) == len(set(keys)) for keys in keys_per_chord.values())
    assert max(len(keys) for keys in keys_per_chord.values()) >= 4

    typed = simulate_typing(build_timeline(notes))
    assert len(typed) == len(notes)
    assert {"!", "@", "$"} <= set(typed)  # Shift + digit
    assert any(c.isupper() for c in typed)  # Shift + letter


def test_edit_trims_transposes_and_retimes(tmp_path, capsys):
    path = tmp_path / "Scale.apno"
    assert cli.main(["convert", str(_song(tmp_path)), "-o", str(path), "--key", "original", "--title", "Scale"]) == 0
    assert cli.main(["edit", str(path), "--start", "0.5", "--end", "0:01.5", "--transpose", "2", "--tempo", "200"]) == 0
    edited = read_script(tmp_path / "Scale (edited).apno")
    assert edited.meta.title == "Scale (edited)"
    assert edited.meta.transpose == 2
    assert [n.start for n in edited.notes] == [0.0, 0.125, 0.25, 0.375]  # 0.5-1.5 s, twice as fast
    assert [n.pitch for n in edited.notes] == [64 + 2, 65 + 2, 67 + 2, 69 + 2]

    capsys.readouterr()
    assert cli.main(["info", str(tmp_path / "Scale (edited).apno")]) == 0
    assert "trimmed to 0:00.5–0:01.5, up 2 semitones, 200% tempo" in capsys.readouterr().out


def test_edit_never_replaces_a_file_unless_told(tmp_path, capsys):
    path = tmp_path / "Scale.apno"
    assert cli.main(["convert", str(_song(tmp_path)), "-o", str(path), "--title", "Scale"]) == 0
    assert cli.main(["edit", str(path), "--title", "Scale", "--tempo", "50"]) == 1
    assert "--force" in capsys.readouterr().err
    assert read_script(path).meta.duration == 2.0
    assert cli.main(["edit", str(path), "--title", "Scale", "--tempo", "50", "--force"]) == 0
    assert read_script(path).meta.duration == 4.0


def test_edit_reports_bad_times_and_impossible_edits(tmp_path, capsys):
    path = tmp_path / "Scale.apno"
    assert cli.main(["convert", str(_song(tmp_path)), "-o", str(path)]) == 0
    assert cli.main(["edit", str(path), "--start", "1:75"]) == 1
    assert cli.main(["edit", str(path), "--start", "soon"]) == 1
    assert cli.main(["edit", str(path), "--start", "0:03", "--end", "0:02"]) == 1
    assert cli.main(["edit", str(path), "--drop", "melody", "--drop", "bass", "--drop", "chords"]) == 1
    errors = capsys.readouterr().err
    assert "m:ss" in errors and "before the end" in errors and "Nothing is left" in errors
