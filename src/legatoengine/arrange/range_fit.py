"""Fits notes into the piano's range by moving them whole octaves."""

from __future__ import annotations

import statistics

from ..models import Note, Role
from .cleanup import merge_duplicates

MELODY_CENTER = 74  # D5: the right hand's home
BASS_CENTER = 43  # G2: the left hand's home


def fold(pitch: int, low: int, high: int) -> int:
    while pitch < low:
        pitch += 12
    while pitch > high:
        pitch -= 12
    return pitch


def center_line(notes: list[Note], role: Role, target: int) -> int:
    """Moves a whole part by octaves so its middle sits near ``target``. Returns the shift."""
    pitches = [n.pitch for n in notes if n.role is role]
    if not pitches:
        return 0
    shift = 12 * round((target - statistics.median(pitches)) / 12)
    for n in notes:
        if n.role is role:
            n.pitch += shift
    return shift


def fit_to_range(notes: list[Note], low: int, high: int, move_lines: bool = False) -> list[Note]:
    """``move_lines`` places melody and bass parts in the usual hand positions first,
    which separated stems need (a singer's melody often sits under the chords)."""
    if move_lines:
        center_line(notes, Role.MELODY, MELODY_CENTER)
        center_line(notes, Role.BASS, BASS_CENTER)
    for n in notes:
        n.pitch = fold(n.pitch, low, high)
    return merge_duplicates(notes)  # folding can put two notes on the same key
