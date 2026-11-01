"""Key detection and choosing a transposition that's easy to play."""

from __future__ import annotations

import numpy as np

from ..layout import Layout, is_black
from ..models import Note

# Krumhansl-Kessler key profiles.
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
MAJOR_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MINOR_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


def pitch_class_profile(notes: list[Note]) -> np.ndarray:
    profile = np.zeros(12)
    for n in notes:
        profile[n.pitch % 12] += min(n.duration, 2.0) * (0.5 + n.velocity / 254)
    return profile


def detect_key(notes: list[Note]) -> tuple[int, str]:
    """(tonic pitch class, "major" or "minor")."""
    profile = pitch_class_profile(notes)
    if not profile.any():
        return 0, "major"
    best = (-2.0, 0, "major")
    for tonic in range(12):
        for mode, template in (("major", MAJOR), ("minor", MINOR)):
            r = float(np.corrcoef(profile, np.roll(template, tonic))[0, 1])
            if r > best[0]:
                best = (r, tonic, mode)
    return best[1], best[2]


def key_name(tonic: int, mode: str) -> str:
    names = MAJOR_NAMES if mode == "major" else MINOR_NAMES
    return f"{names[tonic % 12]} {mode}"


def transposed_key_name(name: str, shift: int) -> str:
    """"Eb major" moved down 3 semitones is "C major"."""
    tonic, _, mode = name.partition(" ")
    names = MAJOR_NAMES if mode == "major" else MINOR_NAMES
    if tonic not in names:
        return name
    return key_name(names.index(tonic) + shift, mode)


def transpose_cost(notes: list[Note], shift: int, layout: Layout) -> float:
    """Lower is easier: fewer black keys (Shift presses) and fewer notes out of range."""
    if not notes:
        return 0.0
    black = sum(is_black(n.pitch + shift) for n in notes)
    outside = sum(not layout.low <= n.pitch + shift <= layout.high for n in notes)
    return (black + 0.5 * outside) / len(notes) + 0.01 * abs(shift)


def choose_transpose(notes: list[Note], layout: Layout, max_shift: int = 6) -> int:
    return min(range(-max_shift, max_shift + 1), key=lambda s: transpose_cost(notes, s, layout))
