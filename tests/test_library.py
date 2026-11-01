import os
from pathlib import Path

from autopiano import cli, library, paths
from autopiano.format.apno import write_script
from autopiano.library import Entry, scan, search, sort_entries, words
from autopiano.models import Note, Script, ScriptMeta


def _entries(*titles: str, folder: str = "") -> list[Entry]:
    return [Entry(Path(f"/library/{folder}/{t}.apno"), t, folder) for t in titles]


def _titles(entries: list[Entry]) -> list[str]:
    return [e.title for e in entries]


def _save(path: Path, title: str, duration: float = 60.0, key: str = "C major", layout: str = "vp61") -> Path:
    meta = ScriptMeta(title=title, duration=duration, key_name=key, source_kind="piano", layout_id=layout)
    return write_script(Script(meta, [Note(60, 0.0, 0.5, key="t", chord=0)]), path)


def test_words_ignore_case_accents_and_punctuation():
    assert words("Für Élise (Op.59)") == ["fur", "elise", "op", "59"]
    assert words("Snowfall - øneheart x reidenshi_MP3") == ["snowfall", "oneheart", "x", "reidenshi", "mp", "3"]
    assert words("BWV846") == ["bwv", "846"]
    assert words("Prelude in C# minor") == words("prelude in c sharp minor")
    assert words("꽃날(Flower Day)") == words("꽃날 flower day")


def test_best_matches_come_first():
    entries = _entries("A Big Idea", "Ideas and Dreams", "Idea 22 - Gibran Alcocer", "Moonlight Sonata")
    found = search(entries, "idea")
    assert found[0].title == "Idea 22 - Gibran Alcocer"
    assert set(_titles(found)) == {"A Big Idea", "Ideas and Dreams", "Idea 22 - Gibran Alcocer"}


def test_every_word_has_to_match():
    entries = _entries("Moonlight Sonata", "Moon River", "Pathétique Sonata")
    assert _titles(search(entries, "moon sonata")) == ["Moonlight Sonata"]
    assert _titles(search(entries, "sonata")) == ["Moonlight Sonata", "Pathétique Sonata"]  # ties keep their order
    assert search(entries, "") == entries
    assert search(entries, "nothing like this") == []


def test_accents_spacing_and_typos_are_forgiven():
    entries = _entries("Für Elise – Beethoven", "Moonlight Sonata", "Nocturne Op. 9 No. 2 – Chopin",
                       "J.S. Bach, Prelude 1, BWV 846", "Snowfall - øneheart x reidenshi", "꽃날(Flower Day)")
    assert _titles(search(entries, "fur elise")) == ["Für Elise – Beethoven"]
    assert _titles(search(entries, "elsie")) == ["Für Elise – Beethoven"]  # two letters swapped
    assert _titles(search(entries, "moonlite")) == ["Moonlight Sonata"]
    assert _titles(search(entries, "chopan op9")) == ["Nocturne Op. 9 No. 2 – Chopin"]
    assert _titles(search(entries, "bwv846")) == ["J.S. Bach, Prelude 1, BWV 846"]
    assert _titles(search(entries, "oneheart")) == ["Snowfall - øneheart x reidenshi"]
    assert _titles(search(entries, "꽃날")) == ["꽃날(Flower Day)"]


def test_short_words_and_numbers_must_be_exact_or_a_start():
    entries = _entries("Car Song", "Idea 2", "Idea 22", "Song of 2024")
    assert search(entries, "cat") == []
    assert _titles(search(entries, "ca")) == ["Car Song"]
    assert _titles(search(entries, "idea 2")) == ["Idea 2", "Idea 22"]
    assert search(entries, "2023") == []


def test_folders_keys_and_piano_size_can_be_searched():
    entries = [
        Entry(Path("/library/Classical/Für Elise.apno"), "Für Elise", "Classical", key_name="A minor", layout_id="vp61"),
        Entry(Path("/library/Bad Apple.apno"), "Bad Apple", "", key_name="Eb minor", layout_id="vp88"),
        Entry(Path("/library/Ama.apno"), "Ama", "", key_name="C major", layout_id="vp61"),
    ]
    assert _titles(search(entries, "classical")) == ["Für Elise"]
    assert _titles(search(entries, "a minor")) == ["Für Elise"]
    assert _titles(search(entries, "88")) == ["Bad Apple"]
    assert _titles(search(entries, "eb minor")) == ["Bad Apple"]
    assert _titles(search(entries, "a")) == ["Ama", "Bad Apple"]  # not Für Elise: part of a key isn't enough


def test_sorting():
    entries = [
        Entry(Path("/l/b.apno"), "Idea 10", duration=30, modified=3),
        Entry(Path("/l/a.apno"), "idea 9", duration=200, modified=1),
        Entry(Path("/l/c.apno"), "Ángel", duration=90, modified=2),
    ]
    assert _titles(sort_entries(entries, "name")) == ["Ángel", "idea 9", "Idea 10"]
    assert _titles(sort_entries(entries, "length")) == ["Idea 10", "Ángel", "idea 9"]
    assert _titles(sort_entries(entries, "newest")) == ["Idea 10", "Ángel", "idea 9"]


def test_scan_reads_subfolders_and_only_changed_files(tmp_path, monkeypatch):
    old = _save(tmp_path / "Old.apno", "Old Song", duration=125)
    os.utime(old, (1_000_000, 1_000_000))
    _save(tmp_path / "Classical" / "Chopin" / "Nocturne.apno", "Nocturne Op. 9 No. 2", key="Eb major")
    _save(tmp_path / ".hidden" / "Secret.apno", "Secret")
    (tmp_path / "Broken.apno").write_bytes(b"not a script")
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "song.m4a").write_bytes(b"audio")

    entries = {e.title: e for e in scan(tmp_path)}
    assert set(entries) == {"Old Song", "Nocturne Op. 9 No. 2", "Broken"}
    assert entries["Nocturne Op. 9 No. 2"].folder == "Classical/Chopin"
    assert entries["Nocturne Op. 9 No. 2"].key_name == "Eb major"
    assert entries["Old Song"].duration == 125 and entries["Old Song"].folder == ""
    assert not entries["Broken"].readable
    assert scan(tmp_path)[-1].title == "Old Song"  # newest first
    assert library.folders(tmp_path) == [tmp_path, tmp_path / "Classical", tmp_path / "Classical" / "Chopin",
                                         tmp_path / "Downloads"]

    reads = []
    real_read = library.read_script
    monkeypatch.setattr(library, "read_script", lambda path: reads.append(path) or real_read(path))
    scan(tmp_path)
    assert reads == []  # nothing changed, so nothing was read again
    _save(old, "Old Song, Trimmed")
    assert "Old Song, Trimmed" in _titles(scan(tmp_path))
    assert reads == [old]


def test_cli_search(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "LIBRARY_DIR", tmp_path)
    _save(tmp_path / "Classical" / "Für Elise.apno", "Für Elise – Beethoven", duration=175, key="A minor")
    _save(tmp_path / "Golden Hour.apno", "Golden Hour - JVKE", duration=209, key="F major")

    assert cli.main(["search", "fur", "elise"]) == 0
    out, err = capsys.readouterr()
    assert "Für Elise – Beethoven  (2:55, A minor)" in out
    assert str(tmp_path / "Classical" / "Für Elise.apno") in out or "Classical/Für Elise.apno" in out
    assert "Golden Hour" not in out
    assert "1 of 2 scripts match" in err

    assert cli.main(["search", "--sort", "name"]) == 0
    out, err = capsys.readouterr()
    assert out.index("Für Elise") < out.index("Golden Hour")
    assert "2 scripts" in err

    assert cli.main(["search", "zzz"]) == 1
    assert "0 of 2 scripts match" in capsys.readouterr().err
