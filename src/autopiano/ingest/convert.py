"""Turns any supported file into raw notes (a Song) by the right path:

- MIDI: read the notes directly.
- Piano recording: the Transkun piano model on the whole recording.
- Full song: BS-RoFormer-SW splits it into stems, SwiftF0 follows the vocal melody,
  MuScriptor transcribes the bass line and the guitar + other stems, and the piano model the
  piano stem. Without MuScriptor's weights (they're gated), SwiftF0 follows the bass line and
  the piano model transcribes piano + guitar + other.
- Auto: separate a few stretches of the song first, then treat it as a piano (solo
  instrument) recording if there's no singer, drums or bass and one instrument stem
  holds almost everything. Otherwise the rest is separated and it's a full song.

Audio that isn't tuned to A440 is measured first, and every model hears it in tune.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import Role, Song
from ..progress import ProgressFn, Stages
from . import cache
from .audio import AudioError, file_hash, load_audio, resample, rms, to_mono, tuning_offset
from .midi import read_midi

MIDI_EXTENSIONS = {".mid", ".midi", ".kar", ".smf"}
SOURCE_KINDS = {
    "auto": "Auto-detect",
    "full": "Full song (vocals, band)",
    "piano": "Piano (or one instrument)",
    "midi": "MIDI file",
}
MIX_RATE = 44100
MODEL_RATE = 16000


def is_midi(path: str | Path) -> bool:
    return Path(path).suffix.lower() in MIDI_EXTENSIONS


def load_song(path: str | Path, kind: str = "auto", progress: ProgressFn | None = None, use_cache: bool = True) -> Song:
    path = Path(path)
    if is_midi(path):
        if kind not in ("auto", "midi"):
            raise AudioError("This is a MIDI file. Choose MIDI or Auto-detect as the source type.")
        song = read_midi(path)
        song.source_hash = file_hash(path)
        return song
    if kind == "midi":
        raise AudioError("This isn't a MIDI file. Choose another source type.")

    digest = file_hash(path)
    if use_cache and (song := cache.load(digest, kind)) is not None:
        song.title, song.source_name = path.stem, path.name
        if progress:
            progress("Done", 1.0)
        return song

    from .separate import ensure_checkpoint, is_downloaded
    from .transcribe_multi import is_ready

    # weights are about the seconds each stage takes on an M1 Pro, per 10 seconds of audio
    # (the one-time download is weighted as if the song were a few minutes long)
    stages = Stages(
        progress,
        [
            ("read", "Reading the audio", 0.1),
            ("models", "Downloading the separation model (699 MB, first time only)", 0 if kind == "piano" or is_downloaded() else 6),
            ("separate", "Separating vocals, bass and instruments", 0 if kind == "piano" else 3.1),
            ("instrument model", "Downloading the instrument model (1.2 GB, first time only)", 0 if kind == "piano" or is_ready() else 10),
            ("tuning", "Checking the tuning", 0.1),
            ("melody", "Finding the melody", 0 if kind == "piano" else 0.05),
            ("bass", "Finding the bass line", 0 if kind == "piano" else 1.2),
            ("instruments", "Transcribing guitar and other instruments", 0 if kind == "piano" else 1.8),
            ("harmony", "Transcribing the notes", 1.3),
            ("beats", "Finding the beat", 0.1),
        ],
    )
    stages.start("read")
    audio = load_audio(path, MIX_RATE)

    complete = True
    if kind == "piano":
        song = _piano(audio, stages)
    else:
        from .separate import joined, release, separate

        if not is_downloaded():
            ensure_checkpoint(stages.start("models"))
        step = stages.start("separate")
        sample = _sample(audio, step) if kind == "auto" else {}
        solo = bool(sample) and _sounds_like_solo_instrument(joined(sample))
        stems = None if solo else separate(audio, step, done=sample)
        release()  # one model at a time: its memory goes to the transcription models
        if solo:
            song = _piano(audio, stages)
        else:
            complete = _instrument_model(stages)
            song = _full_song(audio, stems, stages, complete)

    from ..arrange.tempo import estimate_beats

    stages.start("beats")
    song.tempo, song.beats = estimate_beats(resample(to_mono(audio), MIX_RATE, 22050), 22050)
    song.title, song.source_name, song.source_hash = path.stem, path.name, digest
    if complete:  # without the instrument model, the next conversion tries again
        cache.save(song, kind)
    stages.done()
    return song


def _sample(audio: np.ndarray, step: Callable[[float], None]) -> dict[int, np.ndarray]:
    """Separates a few chunks spread through the song: enough to hear a solo instrument, and
    a full song doesn't separate them again."""
    from .separate import chunk_count, sample_chunks, separate_chunks

    chunks = sample_chunks(audio)
    return separate_chunks(audio, chunks, lambda f: step(f * len(chunks) / chunk_count(audio)))


def _sounds_like_solo_instrument(stems: dict[str, np.ndarray]) -> bool:
    """No singer, drums or bass, and one instrument stem holds almost everything.
    (A separator can file a solo piano under guitar or other, so any of them counts.)"""
    energy = {name: rms(stem) ** 2 for name, stem in stems.items()}
    total = sum(energy.values()) or 1.0
    share = {name: e / total for name, e in energy.items()}
    backing = share["vocals"] + share["drums"] + share["bass"]
    return backing < 0.15 and max(share["piano"], share["guitar"], share["other"]) >= 0.7


def _piano(audio: np.ndarray, stages: Stages) -> Song:
    from . import transcribe_poly

    stages.start("tuning")
    tuning = tuning_offset(audio, MIX_RATE)
    notes, pedals = transcribe_poly.transcribe_polyphonic(audio, stages.start("harmony"), tuning)
    transcribe_poly.release()
    return Song(notes=notes, duration=audio.shape[1] / MIX_RATE, source_kind="piano", pedals=pedals)


def _instrument_model(stages: Stages) -> bool:
    """Gets MuScriptor's weights in place, if they aren't yet. False if they can't be had."""
    from .separate import ModelDownloadError
    from .transcribe_multi import ensure_weights, is_ready

    if is_ready():
        return True
    try:
        ensure_weights(stages.start("instrument model"))
    except ModelDownloadError as e:
        warnings.warn(f"Transcribing without the instrument model. {e}", RuntimeWarning)
        return False
    return True


def _full_song(audio: np.ndarray, stems: dict[str, np.ndarray], stages: Stages, instruments: bool) -> Song:
    """With ``instruments``, MuScriptor transcribes the bass and the guitar + other stems. The models
    run one at a time, each freed before the next, so the memory peak is the largest one's."""
    from . import transcribe_multi, transcribe_poly
    from .transcribe_mono import BASS, VOCALS, transcribe_line

    duration = audio.shape[1] / MIX_RATE
    mix_level = rms(to_mono(audio)) or 1.0
    rest = stems["guitar"] + stems["other"]
    stages.start("tuning")
    tuning = tuning_offset(stems["piano"] + rest, MIX_RATE)  # sliding voices and drums would blur it

    def mono16(*names: str) -> np.ndarray:
        return resample(to_mono(sum(stems[n] for n in names)), MIX_RATE, MODEL_RATE)

    notes = []
    vocals = mono16("vocals")
    melody_step = stages.start("melody")
    if rms(vocals) >= 0.08 * mix_level:
        melody = transcribe_line(vocals, VOCALS, Role.MELODY, melody_step, tuning)
        if sum(n.duration for n in melody) >= 0.08 * duration:  # otherwise it's an instrumental
            notes += melody
    bass = mono16("bass")
    bass_step = stages.start("bass")
    if rms(bass) >= 0.05 * mix_level:
        if instruments:
            notes += transcribe_multi.transcribe_instruments(stems["bass"], bass_step, tuning, transcribe_multi.BASS, Role.BASS)
        else:
            notes += transcribe_line(bass, BASS, Role.BASS, bass_step, tuning)
    others = []
    if instruments:
        others = transcribe_multi.transcribe_instruments(rest, stages.start("instruments"), tuning)
        transcribe_multi.release()
        piano, _ = transcribe_poly.transcribe_polyphonic(stems["piano"], stages.start("harmony", "Transcribing the piano"), tuning)
    else:
        label = "Transcribing the notes (the instrument model couldn't be downloaded)"
        piano, _ = transcribe_poly.transcribe_polyphonic(stems["piano"] + rest, stages.start("harmony", label), tuning)
    transcribe_poly.release()
    return Song(notes=notes + piano + others, duration=duration, source_kind="full")
