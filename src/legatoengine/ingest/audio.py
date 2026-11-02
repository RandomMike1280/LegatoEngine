"""Decodes audio files into float arrays."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff", ".aif", ".wma", ".webm", ".mp4"}


class AudioError(Exception):
    """The file couldn't be decoded. The message is safe to show the user."""


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:32]


def find_program(name: str) -> str | None:
    # Apps started from Finder don't get Homebrew's folders on PATH.
    for candidate in (shutil.which(name), f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def install_hint(program: str) -> str:
    """How to install ffmpeg or Deno on this computer."""
    if sys.platform == "win32":
        package = {"ffmpeg": "Gyan.FFmpeg", "deno": "DenoLand.Deno"}[program]
        return f"winget install {package} (then open a new terminal)"
    return f"brew install {program}"


def find_ffmpeg() -> str | None:
    return find_program("ffmpeg")


def load_audio(path: str | Path, sample_rate: int = 44100) -> np.ndarray:
    """Stereo float32 audio, shape (2, samples), at ``sample_rate``."""
    path = Path(path)
    try:
        import soundfile

        data, file_rate = soundfile.read(path, dtype="float32", always_2d=True)
        audio = data.T
    except Exception:
        audio, file_rate = _ffmpeg_decode(path, sample_rate), sample_rate
    if audio.shape[0] == 1:
        audio = np.repeat(audio, 2, axis=0)
    elif audio.shape[0] > 2:
        audio = audio[:2]
    if file_rate != sample_rate:
        audio = resample(audio, file_rate, sample_rate)
    if audio.shape[1] < sample_rate // 2:
        raise AudioError("This audio is too short to use.")
    return np.ascontiguousarray(audio, dtype=np.float32)


def _ffmpeg_decode(path: Path, sample_rate: int) -> np.ndarray:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise AudioError(f"Reading this kind of file needs ffmpeg. Install it with: {install_hint('ffmpeg')}")
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-vn", "-f", "f32le", "-ac", "2", "-ar", str(sample_rate), "-"]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not result.stdout:
        detail = result.stderr.decode(errors="replace").strip().splitlines()
        raise AudioError(f"Couldn't read this audio file. {detail[-1] if detail else ''}".strip())
    return np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, 2).T


def resample(audio: np.ndarray, from_rate: float, to_rate: float) -> np.ndarray:
    """Works on (samples,) or (channels, samples)."""
    if from_rate == to_rate:
        return audio
    import soxr

    if audio.ndim == 1:
        return soxr.resample(audio, from_rate, to_rate).astype(np.float32)
    return soxr.resample(audio.T, from_rate, to_rate).T.astype(np.float32)


def tuning_offset(audio: np.ndarray, sample_rate: int) -> float:
    """How far the music is tuned from A440, in semitones (-0.5 to 0.5). Old pianos,
    A=432 recordings and sped-up videos are often a third of a semitone off or more."""
    import librosa

    offset = librosa.estimate_tuning(y=resample(to_mono(audio), sample_rate, 22050), sr=22050)
    return float(offset) if np.isfinite(offset) else 0.0


def retune(audio: np.ndarray, sample_rate: int, semitones: float) -> tuple[np.ndarray, float]:
    """Moves audio that is ``semitones`` off A440 back in tune by playing it a little slower
    or faster. Returns the audio and the factor that turns its times back into the original's."""
    if abs(semitones) < 0.05:  # 5 cents: not worth resampling
        return audio, 1.0
    factor = 2 ** (-semitones / 12)
    return resample(audio, sample_rate, sample_rate / factor), factor


def to_mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0) if audio.ndim == 2 else audio


def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(audio, dtype=np.float64)))) if audio.size else 0.0
