"""Checks that the player presses exactly what the converter's own player would.

    uv run python player-app/tests/parity.py fixtures
        writes random scripts and what the Python player makes of them to tests/fixtures,
        which `cargo test` then compares against (see parity.rs)
    uv run python player-app/tests/parity.py check DUMP FILE...
        runs the Rust `dump` example (cargo build --example dump) on real scripts and
        compares its output with the Python player's, file by file

Run from the LegatoEngine folder so `legatoengine` imports from the converter.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

from legatoengine.arrange.possible import make_possible
from legatoengine.format.apno import read_script, write_script
from legatoengine.layout import load_layout
from legatoengine.models import Note, Role, Script, ScriptMeta
from legatoengine.player.timeline import PlaySettings, build_timeline

FIXTURES = Path(__file__).parent / "fixtures"
SETTINGS = [(1.0, "natural"), (0.75, "natural"), (1.5, "natural"), (1.0, "tap"), (1.25, "tap")]


def note_rows(notes):
    return [[n.pitch, n.start, n.duration, n.velocity, int(n.role), n.chord, n.key, int(n.modifier)] for n in notes]


def expected(script: Script) -> dict:
    layout = load_layout(script.meta.layout_id)
    possible, report = make_possible(script.notes, layout)
    timelines = []
    for speed, hold in SETTINGS:
        actions = build_timeline(script.notes, PlaySettings(speed=speed, hold=hold))
        timelines.append({"speed": speed, "tap": hold == "tap",
                          "actions": [[a.time, a.down, a.key] for a in actions]})
    possible_actions = build_timeline(possible, PlaySettings())
    m = script.meta
    return {
        "meta": {"title": m.title, "duration": m.duration, "key_name": m.key_name, "transpose": m.transpose,
                 "layout_id": m.layout_id, "bpm": m.bpm, "source_kind": m.source_kind},
        "notes": note_rows(script.notes),
        "beats": script.beats,
        "timelines": timelines,
        "possible": {
            "notes": note_rows(possible),
            "report": [report.chords, report.moved, report.doubled, report.dropped],
            "actions": [[a.time, a.down, a.key] for a in possible_actions],
        },
    }


def random_script(seed: int, layout_id: str) -> Script:
    """Chords that mix plain, Shift and Ctrl keys, repeated keys, long holds and overlaps."""
    rng = random.Random(seed)
    layout = load_layout(layout_id)
    pitches = sorted(layout.keys)
    notes, t, number = [], 0.0, 0
    for _ in range(rng.randint(120, 260)):
        t += rng.choice([0.0, 0.004, 0.02, 0.05, 0.12, 0.25, 0.5])
        size = rng.choice([1, 1, 2, 3, 4, 5])
        chosen = rng.sample(pitches, size)
        top = max(chosen)
        bottom = min(chosen)
        duration = rng.choice([0.01, 0.05, 0.2, 0.6, 1.5, 9.0])
        for p in chosen:
            role = Role.MELODY if p == top and rng.random() < 0.8 else Role.BASS if p == bottom else Role.HARMONY
            key, modifier = layout.lookup(p)
            notes.append(Note(p, round(t + rng.choice([0, 0, 0.003]), 3), duration * rng.uniform(0.5, 1.5),
                              rng.randint(30, 120), role, chord=number, key=key, modifier=modifier))
        number += rng.choice([1, 1, 1, 2])  # gaps in the numbering, like real scripts
    # a few chords numbered out of time order
    for n in notes[:12]:
        n.chord += 10_000
    beats = [i * 0.5 for i in range(int(t * 2) + 2)]
    meta = ScriptMeta(title=f"Parity {seed}", source_kind="midi", duration=t + 2, bpm=120.0,
                      key_name="Eb major", transpose=-3, layout_id=layout_id)
    return Script(meta=meta, notes=notes, beats=beats)


def short_script() -> Script:
    """Half a second: a plain chord, a chord with a black key, and a melody note."""
    layout = load_layout("vp61")
    notes = []
    for number, (start, chord) in enumerate([(0.0, [(48, Role.BASS), (60, Role.HARMONY), (64, Role.MELODY)]),
                                             (0.2, [(50, Role.BASS), (66, Role.HARMONY), (69, Role.MELODY)]),
                                             (0.4, [(72, Role.MELODY)])]):
        for pitch, role in chord:
            key, modifier = layout.lookup(pitch)
            notes.append(Note(pitch, start, 0.15, 90, role, chord=number, key=key, modifier=modifier))
    meta = ScriptMeta(title="Short test", source_kind="midi", duration=0.6, bpm=120.0, key_name="D major")
    return Script(meta=meta, notes=notes, beats=[0.0, 0.5])


def write_fixtures() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for old in FIXTURES.glob("*"):
        old.unlink()
    for seed, layout_id in [(1, "vp61"), (2, "vp61"), (3, "vp88"), (4, "vp88"), (5, "vp61"), (6, "vp88")]:
        path = write_script(random_script(seed, layout_id), FIXTURES / f"random-{seed}.apno")
        script = read_script(path)  # what the file holds, timings rounded to milliseconds
        (FIXTURES / f"random-{seed}.json").write_text(json.dumps(expected(script)))
        print(f"{path.name}: {len(script.notes)} notes, {script.meta.layout_id}")
    path = write_script(short_script(), FIXTURES / "short.apno")
    (FIXTURES / "short.json").write_text(json.dumps(expected(read_script(path))))


def close(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= 1e-9
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    return a == b


def first_difference(name: str, a, b) -> str | None:
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{name}: {len(a)} items vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            if not close(x, y):
                return f"{name}[{i}]: Python {x} vs Rust {y}"
        return None
    if isinstance(a, dict):
        for k in a:
            if (d := first_difference(f"{name}.{k}", a[k], b.get(k))) is not None:
                return d
        return None
    return None if close(a, b) else f"{name}: Python {a!r} vs Rust {b!r}"


def check(dump: str, files: list[str]) -> int:
    bad = 0
    for file in files:
        script = read_script(file)
        want = expected(script)
        got = json.loads(subprocess.run([dump, file], capture_output=True, text=True, check=True).stdout)
        if (diff := first_difference("", want, got)) is not None:
            bad += 1
            print(f"DIFFERENT {Path(file).name}: {diff}")
    print(f"{len(files) - bad} of {len(files)} scripts match")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["fixtures"]:
        write_fixtures()
    elif sys.argv[1:2] == ["check"]:
        sys.exit(check(sys.argv[2], sys.argv[3:]))
    else:
        sys.exit(__doc__)
