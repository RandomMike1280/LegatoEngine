"""Groups notes into chords and makes sure every key can actually be pressed."""

from __future__ import annotations

from collections import defaultdict

from ..models import Note
from .roles import onset_groups


def group_chords(notes: list[Note], window: float) -> list[list[Note]]:
    """Notes starting within ``window`` of each other are pressed together.
    Each note keeps its original end time."""
    chords = onset_groups(notes, window)
    for chord in chords:
        t = chord[0].start
        for n in chord:
            end = n.end
            n.start = t
            n.duration = max(0.01, end - t)
    return chords


def enforce_key_gaps(notes: list[Note], min_gap: float = 0.02, min_hold: float = 0.01) -> list[Note]:
    """A key has to come up before it can go down again.

    Notes sharing a physical key (C4 is T, C#4 is Shift+T) are spaced so each is
    released ``min_gap`` before the next press. When two presses are too close for
    that, the less important note is dropped.
    """
    by_key: dict[str, list[Note]] = defaultdict(list)
    for n in notes:
        by_key[n.key].append(n)
    kept: list[Note] = []
    for same_key in by_key.values():
        same_key.sort(key=lambda n: (n.start, -n.role))
        lane: list[Note] = []
        for n in same_key:
            if lane:
                prev = lane[-1]
                if n.start - prev.start < min_gap + min_hold:
                    if n.role > prev.role:
                        lane[-1] = n
                    continue
                if prev.end > n.start - min_gap:
                    prev.duration = n.start - min_gap - prev.start
            lane.append(n)
        kept += lane
    kept.sort(key=lambda n: (n.start, n.pitch))
    return kept
