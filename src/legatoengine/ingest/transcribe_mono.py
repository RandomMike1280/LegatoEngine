"""Single-voice transcription for the vocal melody and the bass line.

SwiftF0 gives a pitch for every 16 ms, read off at every 10 ms (or 20 ms) frame. Those
frames are smoothed, then cut into notes wherever the voice stops, the pitch moves by
more than about three quarters of a semitone for long enough (so vibrato doesn't count),
or a new syllable starts on the same pitch (an onset).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np

from ..models import Note, Role

SAMPLE_RATE = 16000
# SwiftF0 hears 46.9-2093.75 Hz, which stops two semitones above a bass guitar's open E
# (41.2 Hz). Lower notes are found by playing the audio at double speed, an octave up.
SWIFT_FMIN, SWIFT_FMAX = 46.875, 2093.75
LOW_SPEED = 2
LOW_LIMIT = 48.0  # Hz; only pitches below this are taken from the double-speed pass


@dataclass(frozen=True)
class LineSettings:
    fmin: float
    fmax: float
    hop: int  # samples at 16 kHz
    min_note: float  # seconds
    confidence: float = 0.5  # how sure SwiftF0 must be that there's a pitch (0.5 is its own calibration)
    split_semitones: float = 0.75
    hold_frames: int = 4  # a pitch change must last this many frames to start a new note
    smooth_frames: int = 9


VOCALS = LineSettings(fmin=80, fmax=1100, hop=160, min_note=0.08, hold_frames=5)
BASS = LineSettings(fmin=32.7, fmax=330, hop=320, min_note=0.1, hold_frames=3, smooth_frames=5)

_detector = None


def _swift_f0():
    global _detector
    if _detector is None:
        from swift_f0 import SwiftF0

        _detector = SwiftF0(spin=False)  # spinning threads would keep CPU cores busy between calls
    return _detector


def _detect(audio: np.ndarray, settings: LineSettings, frame_times: np.ndarray, speed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """SwiftF0's (pitch in Hz, confidence) at the frame nearest each of ``frame_times``. Claiming
    ``speed`` times the sample rate plays the audio that much faster, so every pitch goes up."""
    from scipy.ndimage import median_filter

    result = _swift_f0().detect(
        audio, SAMPLE_RATE * speed, fmin=max(settings.fmin * speed, SWIFT_FMIN), fmax=min(settings.fmax * speed, SWIFT_FMAX)
    )
    times = result.timestamps * speed
    after = np.clip(np.searchsorted(times, frame_times), 0, len(times) - 1)
    before = np.clip(after - 1, 0, None)
    nearest = np.where(np.abs(times[before] - frame_times) < np.abs(times[after] - frame_times), before, after)
    return result.pitch_hz[nearest] / speed, median_filter(result.confidence[nearest], size=3, mode="nearest")


def pitch_track(
    audio: np.ndarray, settings: LineSettings, progress: Callable[[float], None] | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(MIDI pitch per frame, voiced per frame, loudness in dB per frame)."""
    import librosa

    audio = np.ascontiguousarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(audio), initial=0.0))
    if peak > 0:  # both SwiftF0's silence cut and the loudness floor below are absolute levels
        audio = audio / peak
    loud = librosa.feature.rms(y=audio, frame_length=1024, hop_length=settings.hop, center=True)[0]
    loud_db = 20 * np.log10(loud + 1e-9)
    gate = max(np.percentile(loud_db, 95) - 35, -55.0)
    frame_times = np.arange(len(loud)) * settings.hop / SAMPLE_RATE
    speeds = [1, LOW_SPEED] if settings.fmin < SWIFT_FMIN else [1]
    pitch, voiced = np.zeros(len(loud)), np.zeros(len(loud), bool)
    for i, speed in enumerate(speeds):
        hz, confidence = _detect(audio, settings, frame_times, speed)
        heard = (confidence >= settings.confidence) & (loud_db >= gate) & (hz > 0)
        if speed != 1:  # the faster pass only fills in what the normal one can't hear
            heard &= ~voiced & (hz < LOW_LIMIT)
        pitch, voiced = np.where(heard, hz, pitch), voiced | heard
        if progress:
            progress((i + 1) / len(speeds))
    midi = 69 + 12 * np.log2(np.maximum(pitch, 1e-3) / 440)
    return midi, voiced, loud_db


def _rearticulated(loudness: np.ndarray | None, i: int, rise_db: float = 6.0) -> bool:
    """A new syllable on the same pitch dips and comes back up. Onset detectors also
    fire on vibrato, which doesn't change the loudness much."""
    if loudness is None:
        return True
    before = loudness[max(0, i - 6) : i + 1]
    after = loudness[i : i + 4]
    return len(before) > 0 and len(after) > 0 and float(after.max() - before.min()) >= rise_db


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index ranges where ``mask`` is True."""
    padded = np.concatenate([[False], mask, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[::2], edges[1::2]))


def segment_notes(
    midi: np.ndarray,
    voiced: np.ndarray,
    frame_time: float,
    settings: LineSettings,
    onsets: Iterable[int] = (),
    loudness: np.ndarray | None = None,
) -> list[Note]:
    from scipy.ndimage import median_filter

    onset_frames = set(int(o) for o in onsets)
    smooth = midi.astype(float).copy()
    runs = _runs(np.asarray(voiced, dtype=bool))
    for a, b in runs:
        size = min(settings.smooth_frames, b - a)
        smooth[a:b] = median_filter(midi[a:b], size=size, mode="nearest")

    pieces: list[tuple[int, int]] = []  # [start frame, end frame)
    min_frames = settings.min_note / frame_time
    for a, b in runs:
        start, deviation_start = a, None
        for i in range(a + 1, b):
            ref = float(np.median(smooth[max(start, i - 20) : i]))
            split_at = None
            if abs(smooth[i] - ref) > settings.split_semitones:
                if deviation_start is None:
                    deviation_start = i
                if i - deviation_start + 1 >= settings.hold_frames:
                    split_at = deviation_start
            else:
                deviation_start = None
            if split_at is None and i in onset_frames and i - start >= min_frames and _rearticulated(loudness, i):
                split_at = i
            if split_at is not None and split_at > start:
                pieces.append((start, split_at))
                start, deviation_start = split_at, None
        pieces.append((start, b))

    peak = float(np.percentile(loudness, 95)) if loudness is not None and len(loudness) else 0.0
    notes: list[Note] = []
    for start, end in pieces:
        if end - start < min_frames:
            continue
        pitch = int(round(float(np.median(midi[start:end]))))
        velocity = 80
        if loudness is not None:
            level = float(np.mean(loudness[start:end]))
            velocity = int(40 + 70 * np.clip((level - (peak - 30)) / 30, 0, 1))
        note = Note(pitch, start * frame_time, (end - start) * frame_time, velocity)
        prev = notes[-1] if notes else None
        if prev and prev.pitch == pitch and note.start - prev.end <= 0.03 and start not in onset_frames:
            prev.duration = note.end - prev.start  # the same note, broken by a wobble
            prev.velocity = max(prev.velocity, velocity)
        else:
            notes.append(note)
    return notes


def transcribe_line(
    audio: np.ndarray,
    settings: LineSettings,
    role: Role,
    progress: Callable[[float], None] | None = None,
    tuning: float = 0.0,
) -> list[Note]:
    """``audio`` is mono float32 at 16 kHz, ``tuning`` how many semitones it is off A440."""
    import librosa

    midi, voiced, loud = pitch_track(audio, settings, progress)
    midi = midi - tuning
    onsets = librosa.onset.onset_detect(y=audio, sr=SAMPLE_RATE, hop_length=settings.hop, backtrack=True, units="frames")
    notes = segment_notes(midi, voiced, settings.hop / SAMPLE_RATE, settings, onsets, loud)
    for n in notes:
        n.role = role
    return notes
