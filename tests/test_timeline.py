import random

import pytest

from autopiano.layout import load_layout
from autopiano.models import Modifier, Note, Role
from autopiano.player.timeline import PlaySettings, build_timeline, expected_modifiers, simulate_typing

LAYOUT = load_layout("vp61")
SHIFTED = dict(zip("1234567890", "!@#$%^&*()"))


def note(pitch, start, duration=0.2, chord=0):
    key, modifier = LAYOUT.lookup(pitch)
    return Note(pitch, start, duration, 80, Role.HARMONY, chord=chord, key=key, modifier=modifier)


def typed(n: Note) -> str:
    return SHIFTED.get(n.key, n.key.upper()) if n.modifier is Modifier.SHIFT else n.key


def check_invariants(actions, settings=PlaySettings()):
    """Shared rules every timeline must follow."""
    shift = False
    down: dict[str, float] = {}
    last_up: dict[str, float] = {}
    times = [a.time for a in actions]
    assert times == sorted(times)
    for a in actions:
        if a.key == "shift":
            shift = a.down
            continue
        if a.down:
            assert a.key not in down, f"{a.key} pressed twice without a release"
            if a.key in last_up:
                assert a.time - last_up[a.key] >= settings.min_regap - 1e-9
            down[a.key] = a.time
        else:
            assert a.key in down, f"{a.key} released without a press"
            assert not shift, f"{a.key} released while Shift is held"
            assert a.time > down.pop(a.key)
            last_up[a.key] = a.time
    assert not down, f"keys left down: {down}"
    assert not shift


def test_chord_presses_plain_keys_before_shifted_keys():
    notes = [note(36, 0, chord=0), note(39, 0, chord=0), note(40, 0, chord=0), note(42, 0.5, chord=1), note(60, 1.0, chord=2)]
    actions = build_timeline(notes)
    assert simulate_typing(actions) == "13@$t"
    check_invariants(actions)


def test_random_songs_follow_all_rules():
    rng = random.Random(7)
    for _ in range(30):
        notes, t, chord = [], 0.0, 0
        last_start: dict[str, float] = {}
        expected = []
        for _ in range(60):
            t += rng.choice([0.03, 0.06, 0.1, 0.25])
            pitches = rng.sample(range(36, 97), rng.randint(1, 6))
            group = []
            for p in pitches:
                key, _ = LAYOUT.lookup(p)
                if any(n.key == key for n in group) or t - last_start.get(key, -1) < 0.05:
                    continue  # the arranger never asks for these
                group.append(note(p, t, rng.choice([0.01, 0.05, 0.3, 1.5]), chord))
                last_start[key] = t
            if group:
                notes += group
                plain = sorted((n for n in group if n.modifier is Modifier.NONE), key=lambda n: n.pitch)
                shifted = sorted((n for n in group if n.modifier is Modifier.SHIFT), key=lambda n: n.pitch)
                expected += [typed(n) for n in plain + shifted]
                chord += 1
        actions = build_timeline(notes)
        check_invariants(actions)
        assert simulate_typing(actions) == "".join(expected)


def test_key_is_released_before_it_is_pressed_again():
    # C4 and C#4 share the T key.
    notes = [note(60, 0.0, 0.5, chord=0), note(61, 0.3, 0.2, chord=1)]
    actions = build_timeline(notes)
    t_events = [a for a in actions if a.key == "t"]
    assert [a.down for a in t_events] == [True, False, True, False]
    assert t_events[2].time - t_events[1].time >= 0.017
    check_invariants(actions)


def test_speed_scales_time():
    notes = [note(60, 0.0, 0.4, chord=0), note(62, 1.0, 0.4, chord=1)]
    actions = build_timeline(notes, PlaySettings(speed=2.0))
    assert [a.time for a in actions if a.down] == pytest.approx([0.0, 0.5])
    assert [a.time for a in actions if not a.down] == pytest.approx([0.2, 0.7])


def test_tap_mode_releases_quickly():
    notes = [note(60, 0.0, 2.0, chord=0)]
    actions = build_timeline(notes, PlaySettings(hold="tap", tap_time=0.03))
    assert [(a.time, a.down) for a in actions] == [(0.0, True), (0.03, False)]


def test_expected_modifiers_inside_a_shift_group():
    notes = [note(61, 0.0, 0.3, chord=0)]
    actions = build_timeline(notes)
    assert [(a.key, a.down) for a in actions] == [("shift", True), ("t", True), ("shift", False), ("t", False)]
    assert expected_modifiers(actions, 1) == {"shift"}
    assert expected_modifiers(actions, 3) == set()
