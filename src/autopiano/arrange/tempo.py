"""Beat grids and optional quantization."""

from __future__ import annotations

import bisect

import numpy as np

from ..models import Note


def estimate_beats(audio: np.ndarray, sample_rate: int) -> tuple[float, list[float]]:
    """(BPM, beat times in seconds) for a mono signal."""
    import librosa

    tempo, frames = librosa.beat.beat_track(y=audio, sr=sample_rate, units="frames")
    times = librosa.frames_to_time(frames, sr=sample_rate)
    bpm = float(np.atleast_1d(tempo)[0])
    return round(bpm, 2), [round(float(t), 4) for t in times]


def subdivide(beats: list[float], subdivision: int) -> list[float]:
    grid = []
    for b0, b1 in zip(beats, beats[1:]):
        grid += [b0 + k * (b1 - b0) / subdivision for k in range(subdivision)]
    if beats:
        grid.append(beats[-1])
    return grid


def quantize_chords(chords: list[list[Note]], beats: list[float], strength: float, subdivision: int = 4) -> None:
    """Pulls each chord toward the nearest grid point. ``strength`` 0 leaves timing
    alone, 1 snaps fully. Chords outside the beat grid aren't touched."""
    if strength <= 0 or len(beats) < 2:
        return
    grid = subdivide(beats, subdivision)
    for chord in chords:
        t = chord[0].start
        if not grid[0] <= t <= grid[-1]:
            continue
        i = bisect.bisect_left(grid, t)
        nearest = min(grid[max(0, i - 1) : i + 1], key=lambda g: abs(g - t))
        moved = t + strength * (nearest - t)
        for n in chord:
            n.start = moved
