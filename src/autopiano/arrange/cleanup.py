"""Removes transcription noise: too-short or too-quiet notes, double strikes and overtones."""

from __future__ import annotations

from collections import defaultdict

from ..models import Note, Role

OVERTONE_INTERVALS = (12, 19, 24)  # octave, octave + fifth, two octaves


def clean(
    notes: list[Note],
    min_duration: float = 0.0,
    min_velocity: int = 1,
    merge_window: float = 0.03,
    remove_overtones: bool = False,
) -> list[Note]:
    notes = [n for n in notes if n.duration >= min_duration and n.velocity >= min_velocity and 0 <= n.pitch <= 127]
    notes = merge_duplicates(notes, merge_window)
    if remove_overtones:
        notes = drop_overtones(notes)
    return notes


def merge_duplicates(notes: list[Note], window: float = 0.03) -> list[Note]:
    """Two strikes of one pitch within ``window`` become one note; an earlier note
    still sounding when the pitch is struck again is cut short."""
    by_pitch: dict[int, list[Note]] = defaultdict(list)
    for n in notes:
        by_pitch[n.pitch].append(n)
    out: list[Note] = []
    for same in by_pitch.values():
        same.sort(key=lambda n: n.start)
        current = same[0].copy()
        for n in same[1:]:
            if n.start - current.start <= window:
                end = max(current.end, n.end)
                current.velocity = max(current.velocity, n.velocity)
                current.role = max(current.role, n.role)
                current.duration = end - current.start
                continue
            if n.start < current.end:
                current.duration = n.start - current.start
            out.append(current)
            current = n.copy()
        out.append(current)
    out.sort(key=lambda n: (n.start, n.pitch))
    return out


def drop_overtones(notes: list[Note], onset_window: float = 0.05) -> list[Note]:
    """Audio transcription often reports a quiet copy of a loud note an octave or a
    twelfth higher. Those ghosts are dropped; real doublings are about as loud."""
    ordered = sorted(notes, key=lambda n: n.start)
    ghosts: set[int] = set()
    lo = 0
    for i, n in enumerate(ordered):
        if n.role is not Role.HARMONY:
            continue
        while ordered[lo].start < n.start - onset_window:
            lo += 1
        j = lo
        while j < len(ordered) and ordered[j].start <= n.start + onset_window:
            m = ordered[j]
            if (
                j != i
                and n.pitch - m.pitch in OVERTONE_INTERVALS
                and m.velocity >= 1.5 * n.velocity
                and min(n.end, m.end) - max(n.start, m.start) >= 0.7 * n.duration
            ):
                ghosts.add(i)
                break
            j += 1
    return [n for i, n in enumerate(ordered) if i not in ghosts]
