"""Turns an arranged script into the exact key presses the player sends.

Holding Shift while pressing a white key would play the black key instead, so each
chord is pressed in groups: plain keys first, then Shift down, the black keys, Shift
up, then the same for Ctrl. Key releases are moved out of those modifier windows,
and a key is always released long enough before it is pressed again.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass

from ..models import Modifier, Note

MODIFIER_KEYS = {Modifier.SHIFT: "shift", Modifier.CTRL: "ctrl"}
MODIFIER_NAMES = frozenset(MODIFIER_KEYS.values())
_GROUP_ORDER = (Modifier.NONE, Modifier.SHIFT, Modifier.CTRL)


@dataclass(slots=True, frozen=True)
class Action:
    time: float  # seconds of real time from the start of the song (speed already applied)
    down: bool
    key: str  # physical key such as "t", or "shift" / "ctrl"


@dataclass
class PlaySettings:
    speed: float = 1.0
    hold: str = "natural"  # "natural" holds keys for the note length, "tap" lets go right away
    tap_time: float = 0.03
    max_hold: float = 8.0
    press_gap: float = 0.001  # between key events inside one chord
    min_regap: float = 0.017  # a key stays up at least this long (about one frame) before a re-press


def build_timeline(notes: list[Note], settings: PlaySettings | None = None) -> list[Action]:
    s = settings or PlaySettings()
    gap = s.press_gap
    chords: dict[int, list[Note]] = defaultdict(list)
    for n in notes:
        chords[n.chord].append(n)
    ordered = sorted(chords.values(), key=lambda ns: min(n.start for n in ns))

    presses: list[tuple[float, str, str]] = []  # (time, key, modifier key or "")
    windows: list[tuple[float, float]] = []  # when a modifier is held
    holds: list[list] = []  # [press time, release time, key]
    cursor = float("-inf")
    for chord in ordered:
        t = max(min(n.start for n in chord) / s.speed, cursor)
        for modifier in _GROUP_ORDER:
            group = sorted((n for n in chord if n.modifier is modifier), key=lambda n: n.pitch)
            if not group:
                continue
            mod_key = MODIFIER_KEYS.get(modifier, "")
            if mod_key:
                presses.append((t, mod_key, ""))
                window_start = t
                t += gap
            for n in group:
                presses.append((t, n.key, mod_key))
                hold = s.tap_time if s.hold == "tap" else min(n.duration / s.speed, s.max_hold)
                holds.append([t, t + max(hold, gap), n.key])
                t += gap
            if mod_key:
                presses.append((t, mod_key, "release"))
                windows.append((window_start, t))
                t += gap
        cursor = t

    _move_releases_out_of_windows(holds, windows, gap)
    _release_before_repress(holds, windows, gap, s.min_regap)

    actions = [Action(t, not (mod == "release"), key) for t, key, mod in presses]
    actions += [Action(release, False, key) for _, release, key in holds]
    actions.sort(key=lambda a: a.time)  # stable: presses keep their order at equal times
    return actions


def _window_containing(windows: list[tuple[float, float]], starts: list[float], t: float):
    i = bisect.bisect_right(starts, t) - 1
    if i >= 0 and windows[i][0] <= t <= windows[i][1]:
        return windows[i]
    return None


def _move_releases_out_of_windows(holds, windows, gap):
    starts = [w[0] for w in windows]
    for hold in holds:
        press, release, _ = hold
        w = _window_containing(windows, starts, release)
        if w is None:
            continue
        if press < w[0] - gap / 2:
            hold[1] = w[0] - gap / 2  # let go just before the modifier goes down
        else:
            hold[1] = w[1] + gap / 2  # pressed inside this window: let go after it


def _release_before_repress(holds, windows, gap, min_regap):
    starts = [w[0] for w in windows]
    by_key: dict[str, list[list]] = defaultdict(list)
    for hold in holds:
        by_key[hold[2]].append(hold)
    for key_holds in by_key.values():
        key_holds.sort(key=lambda h: h[0])
        for current, following in zip(key_holds, key_holds[1:]):
            latest = following[0] - min_regap
            if current[1] <= latest:
                continue
            if latest > current[0]:
                release = latest
                w = _window_containing(windows, starts, release)
                if w is not None and w[0] - gap / 2 > current[0]:
                    release = w[0] - gap / 2
            else:
                release = current[0] + (following[0] - current[0]) / 2  # too close: best effort
            current[1] = release


def expected_modifiers(actions: list[Action], index: int) -> set[str]:
    """Modifiers that should be held just before ``actions[index]`` is sent."""
    held: set[str] = set()
    for a in actions[:index]:
        if a.key in MODIFIER_NAMES:
            (held.add if a.down else held.discard)(a.key)
    return held


_SHIFTED = dict(zip("1234567890", "!@#$%^&*()"))


def simulate_typing(actions: list[Action]) -> str:
    """The text a US keyboard would type if these actions went into a text field."""
    shift = False
    out = []
    for a in actions:
        if a.key == "shift":
            shift = a.down
        elif a.down and a.key not in MODIFIER_NAMES:
            out.append(_SHIFTED.get(a.key, a.key.upper()) if shift else a.key)
    return "".join(out)
