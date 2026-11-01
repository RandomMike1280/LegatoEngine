"""Small piano synthesizers. `render_felt` is the soft felt piano with a lofi finish that ▶ Listen plays;
`render` is a plain, clean piano tone, which the tests turn into audio for the transcription models."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .models import Note

SAMPLE_RATE = 22050
MAX_RING = 3.0  # seconds a note can ring
RELEASE = 0.12  # seconds of fade after the key is let go
FELT_RING = 2.8  # felt-covered hammers die away sooner than bare ones
FELT_RELEASE = 0.25  # and the dampers are soft too
ROOM_TAIL = 1.2  # seconds of room sound after the last note


@lru_cache(maxsize=256)
def _tone(pitch: int, sample_rate: int) -> np.ndarray:
    """One struck note at full velocity, MAX_RING + RELEASE long."""
    f0 = 440.0 * 2 ** ((pitch - 69) / 12)
    t = np.arange(int((MAX_RING + RELEASE) * sample_rate)) / sample_rate
    tone = np.zeros_like(t)
    brightness = (f0 / 261.6) ** 0.4
    for k in range(1, 9):
        fk = k * f0 * np.sqrt(1 + 0.0004 * k * k)  # piano strings are slightly inharmonic
        if fk >= sample_rate / 2:
            break
        tone += np.sin(2 * np.pi * fk * t) / k**1.3 * np.exp(-t * (0.8 + 0.7 * k) * brightness)
    attack = min(len(t), int(0.004 * sample_rate))
    tone[:attack] *= np.linspace(0, 1, attack)
    return (tone / np.abs(tone).max()).astype(np.float32)


def render(notes: list[Note], sample_rate: int = SAMPLE_RATE, gain: float = 0.3) -> np.ndarray:
    """Mono float32 audio of the notes."""
    if not notes:
        return np.zeros(0, np.float32)
    total = max(n.start + min(n.duration, MAX_RING) + RELEASE for n in notes)
    out = np.zeros(int(total * sample_rate) + 1, np.float32)
    for n in notes:
        hold = min(n.duration, MAX_RING)
        length = int((hold + RELEASE) * sample_rate)
        seg = _tone(n.pitch, sample_rate)[:length] * ((n.velocity / 127) ** 1.5)
        fade_from = int(hold * sample_rate)
        seg[fade_from:] *= np.exp(-np.arange(length - fade_from) / (0.03 * sample_rate))
        start = int(n.start * sample_rate)
        end = min(len(out), start + length)
        out[start:end] += seg[: end - start]
    return np.tanh(out * gain).astype(np.float32)


# ---- the felt piano


@lru_cache(maxsize=96)
def _felt_tone(pitch: int, sample_rate: int) -> np.ndarray:
    """One felt-hammered note, FELT_RING + FELT_RELEASE long. Row 0 is a soft touch;
    row 1 is what a harder strike adds: higher overtones and a firmer knock."""
    from scipy.signal import butter, sosfilt

    f0 = 440.0 * 2 ** ((pitch - 69) / 12)
    n = int((FELT_RING + FELT_RELEASE) * sample_rate)
    t = np.arange(n) / sample_rate  # double precision keeps the phase of high overtones exact
    t32 = t.astype(np.float32)
    rng = np.random.default_rng(pitch)
    stiffness = 0.00012 * 2 ** ((pitch - 60) / 15)  # treble strings are stiffer, so their overtones run sharp
    sustain = float(np.clip(3.5 * 2 ** (-(pitch - 45) / 22), 0.5, 5.0))  # seconds; the bass rings longest
    detune = 2 ** (0.9 / 1200)  # each note has two strings, a hair apart in tune
    tone = np.zeros((2, n), np.float32)
    for k in range(1, 13):
        fk = k * f0 * np.sqrt(1 + stiffness * k * k)
        soft = k**-2.2 * np.exp(-fk / 1800)  # the felt swallows most overtones
        hard = k**-1.2 * np.exp(-fk / 4000) if k > 1 else 0.0
        if fk > 0.45 * sample_rate or max(soft, hard) < 1e-3:
            break
        slow = sustain / (1 + 0.45 * (k - 1))  # higher partials fade sooner
        envelope = 0.55 * np.exp(t32 * np.float32(-7 / slow)) + 0.45 * np.exp(t32 * np.float32(-1 / slow))
        # the two strings together beat gently, the slow shimmer of a real piano
        beat = 0.8 + 0.2 * np.cos(t32 * np.float32(2 * np.pi * fk * (detune - 1 / detune)) + np.float32(rng.uniform(0, 2 * np.pi)))
        wave = np.sin(2 * np.pi * fk * t + rng.uniform(0, 2 * np.pi)).astype(np.float32)
        wave *= envelope * beat
        tone[0] += soft * wave
        tone[1] += hard * wave
    tone[0] *= 1 - np.exp(-t32 / np.float32(0.009))  # felt presses into the string rather than striking it
    tone[1] *= 1 - np.exp(-t32 / np.float32(0.003))
    tone /= np.abs(tone[0]).max()

    def knock(seconds: float, band: list[float], level: float) -> np.ndarray:
        """The hammer's thud: a short burst of noise, filtered."""
        length = int(4 * seconds * sample_rate)
        burst = rng.standard_normal(length) * np.exp(-np.arange(length) / (seconds * sample_rate))
        burst = sosfilt(butter(2, band, "bandpass", fs=sample_rate, output="sos"), burst)
        return level * burst / np.abs(burst).max()

    thud = knock(0.014, [70, 900], 0.12)
    click = knock(0.004, [1200, min(4000, 0.45 * sample_rate)], 0.05)
    tone[0, : len(thud)] += thud
    tone[1, : len(click)] += click
    return tone


@lru_cache(maxsize=2)
def _room(sample_rate: int) -> np.ndarray:
    """The impulse response of a small, soft-furnished room, one row per ear."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(3)
    t = np.arange(int(1.4 * sample_rate)) / sample_rate
    response = rng.standard_normal((2, len(t))) * np.exp(-6.9 * t / 1.1)  # fades 60 dB in 1.1 s
    response = sosfilt(butter(1, 2500, "lowpass", fs=sample_rate, output="sos"), response, axis=1)
    response[:, : int(0.012 * sample_rate)] = 0  # the first reflections arrive a moment late
    return (response / np.sqrt((response**2).sum(axis=1, keepdims=True))).astype(np.float32)


@lru_cache(maxsize=2)
def _hiss(sample_rate: int) -> np.ndarray:
    """Ten seconds of faint tape hiss, one row per ear; it repeats unnoticed."""
    from scipy.signal import butter, sosfilt

    noise = np.random.default_rng(5).standard_normal((2, 10 * sample_rate))
    noise = sosfilt(butter(2, [400, min(5000, 0.45 * sample_rate)], "bandpass", fs=sample_rate, output="sos"), noise, axis=1)
    return (0.0035 * noise / noise.std()).astype(np.float32)


def render_felt(notes: list[Note], sample_rate: int = SAMPLE_RATE, sustain: bool = False) -> np.ndarray:
    """Stereo float32 audio (frames × 2) of the notes on a soft felt piano with a lofi finish:
    warm and a little muffled, a slow tape wobble, faint hiss and crackle, and a small room.
    With ``sustain``, the pedal is down throughout: every note rings on after its key is let go."""
    if not notes:
        return np.zeros((0, 2), np.float32)
    sounding = _with_pedal(notes) if sustain else [n.duration for n in notes]
    end = max(n.start + min(s, FELT_RING) + FELT_RELEASE for n, s in zip(notes, sounding))
    frames = int((end + ROOM_TAIL) * sample_rate) + 1
    mix = np.zeros((2, frames), np.float32)
    damper = np.exp(-np.arange(int(FELT_RELEASE * sample_rate) + 1) / (0.06 * sample_rate)).astype(np.float32)
    for n, s in zip(notes, sounding):
        hold = int(min(s, FELT_RING) * sample_rate)
        length = hold + len(damper) - 1
        tone = _felt_tone(n.pitch, sample_rate)
        touch = n.velocity / 127
        note = (tone[0, :length] + touch**1.5 * tone[1, :length]) * (0.2 + 0.8 * touch**1.8)
        note[hold:] *= damper[: length - hold]
        start = int(n.start * sample_rate)
        stop = min(frames, start + length)
        angle = (np.clip((n.pitch - 64) / 48, -0.5, 0.5) + 1) * np.pi / 4  # low notes a little left, high ones right
        mix[0, start:stop] += np.cos(angle) * note[: stop - start]
        mix[1, start:stop] += np.sin(angle) * note[: stop - start]
    return np.ascontiguousarray(_lofi(mix, sample_rate).T)


def _with_pedal(notes: list[Note]) -> list[float]:
    """How long each note sounds with the sustain pedal down: until it dies away, or until its
    key is struck again and the hammer stops the string that was still ringing."""
    sounding = [FELT_RING] * len(notes)
    last: dict[int, int] = {}
    for i in sorted(range(len(notes)), key=lambda i: notes[i].start):
        pitch = notes[i].pitch
        if pitch in last:
            before = last[pitch]
            sounding[before] = min(sounding[before], notes[i].start - notes[before].start)
        last[pitch] = i
    return sounding


def _lofi(mix: np.ndarray, sample_rate: int) -> np.ndarray:
    from scipy.signal import butter, oaconvolve, sosfilt

    frames = mix.shape[1]
    mix = np.tanh(1.4 * mix * (0.8 / max(float(np.abs(mix).max()), 1e-9))) / np.tanh(1.4)  # a touch of tape saturation
    # an old cassette's top end, and nothing below the piano's lowest string
    filters = np.vstack([butter(2, 4500, "lowpass", fs=sample_rate, output="sos"),
                         butter(1, 40, "highpass", fs=sample_rate, output="sos")])
    mix = sosfilt(filters.astype(np.float32), mix, axis=1)
    # wow and flutter: the tape speed drifts, bending the pitch by a few cents (worked out every 64 samples)
    coarse = np.arange(0, frames + 64, 64)
    t = coarse / sample_rate
    delay = 0.0009 * np.sin(2 * np.pi * 0.53 * t) + 0.0004 * np.sin(2 * np.pi * 0.31 * t + 1) + 0.00003 * np.sin(2 * np.pi * 5.7 * t)
    read_at = np.interp(np.arange(frames), coarse, coarse - (delay - delay.min()) * sample_rate)
    mix = np.stack([np.interp(read_at, np.arange(frames), channel) for channel in mix]).astype(np.float32)
    room = _room(sample_rate)
    mix = 0.85 * mix + 0.25 * oaconvolve(mix, room, axes=1)[:, :frames]
    mix *= 0.85 / max(float(np.abs(mix).max()), 1e-9)
    # hiss throughout, and now and then a crackle of dust
    hiss = _hiss(sample_rate)
    mix += np.tile(hiss, (1, frames // hiss.shape[1] + 1))[:, :frames]
    rng = np.random.default_rng(frames)
    tick = rng.standard_normal(48) * np.exp(-np.arange(48) / 6)
    for at in rng.integers(0, max(1, frames - 48), rng.poisson(2.5 * frames / sample_rate)):
        mix[:, at : at + 48] += rng.uniform(0.004, 0.03) * rng.choice((-1, 1)) * tick
    return np.clip(mix, -1, 1).astype(np.float32)
