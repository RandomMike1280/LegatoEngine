"""Multi-instrument transcription with MuScriptor (Kyutai and Mirelo, 2026).

In full songs it hears the bass stem and the guitar + other stems, while Transkun keeps the
piano stem. MuScriptor is a language model over notes: it listens to 5 s at a time and writes
down each note with its instrument. On 40 test songs it found far more of the guitar, string
and synth notes than Transkun (F1 0.65 against 0.50 for the chords, with Transkun keeping the
piano stem) and more of the bass line (0.88 against SwiftF0's 0.82). Given every part at once
it misses notes, which is why the piano stays with Transkun.

Its weights (1.2 GB, CC BY-NC 4.0: non-commercial use only) are gated on Hugging Face: only an
account that accepted the model's conditions can download them. The first time, they're taken
from the Hugging Face cache, or downloaded with the account signed in on this Mac, checked,
and linked into the models folder.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
from typing import Callable

import numpy as np

from ..models import Note, Role
from ..paths import MODELS_DIR
from .audio import retune, to_mono
from .separate import ModelDownloadError

SAMPLE_RATE = 44100
REPO = "MuScriptor/muscriptor-medium"
REVISION = "f32236969308476e01fd3aae67357de5feb05a2d"
WEIGHTS_SIZE = 1_228_144_472
WEIGHTS_SHA256 = "ac80adbdf85d87231735fd948af7013441c0afced316c4e9067fd5d8a7fb97ec"
# MuScriptor reads its architecture from a config.json next to the weights
CONFIG = {"model_type": "muscriptor", "variant": "medium", "dim": 1024, "num_heads": 16, "num_layers": 24, "card": 1395}
FOLDER = MODELS_DIR / "MuScriptor-medium"
LAG = 0.013  # seconds: its notes start this much late (10-15 ms on every stem tested)
BASS = ["electric_bass", "acoustic_bass"]
GATED_HELP = (
    "The instrument model (MuScriptor) needs a free Hugging Face account. Accept its conditions at "
    "https://huggingface.co/MuScriptor/muscriptor-medium, then sign in on this Mac by running "
    "`uvx --from huggingface_hub hf auth login` in Terminal."
)

_model = None
_model_device = None


def weights_path() -> Path:
    return FOLDER / "model.safetensors"


def is_ready() -> bool:
    path = weights_path()
    return path.exists() and path.stat().st_size == WEIGHTS_SIZE and (FOLDER / "config.json").exists()


def ensure_weights(progress: Callable[[float], None] | None = None) -> Path:
    """Links the weights from the Hugging Face cache, downloading them first if they aren't there."""
    if not is_ready():
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, LocalEntryNotFoundError, RepositoryNotFoundError

        try:
            cached = Path(hf_hub_download(REPO, "model.safetensors", revision=REVISION)).resolve()
        except (GatedRepoError, RepositoryNotFoundError) as e:
            raise ModelDownloadError(GATED_HELP) from e
        except HfHubHTTPError as e:
            if getattr(e.response, "status_code", None) in (401, 403):
                raise ModelDownloadError(GATED_HELP) from e
            raise ModelDownloadError(f"Couldn't download the instrument model (1.2 GB): {e}") from e
        except (LocalEntryNotFoundError, OSError) as e:
            raise ModelDownloadError(f"Couldn't download the instrument model (1.2 GB): {e}") from e
        if progress:
            progress(0.5)
        digest = hashlib.sha256()
        with open(cached, "rb") as f:
            while block := f.read(1 << 20):
                digest.update(block)
        if digest.hexdigest() != WEIGHTS_SHA256:
            raise ModelDownloadError("The instrument model download was damaged. Try again.")
        FOLDER.mkdir(parents=True, exist_ok=True)
        part = weights_path().with_name("model.safetensors.part")
        part.unlink(missing_ok=True)
        try:
            try:
                os.link(cached, part)  # no second copy of 1.2 GB on the same disk
            except OSError:
                shutil.copyfile(cached, part)
            (FOLDER / "config.json").write_text(json.dumps(CONFIG))
            part.replace(weights_path())
        finally:
            part.unlink(missing_ok=True)
    if progress:
        progress(1.0)
    return weights_path()


@contextlib.contextmanager
def _quiet():
    """MuScriptor prints timings for every chunk, some to stdout and some to stderr."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


def _load(device: str):
    global _model, _model_device
    if _model is None or _model_device != device:
        import muscriptor.transcription_model as mt
        from safetensors.torch import load_file

        from .separate import free_gpu_memory

        release()
        # MuScriptor reads the weights straight onto the GPU and halves them there, which takes
        # 1.1 GB more memory at the peak than copying them over from the CPU
        mt.load_file = lambda path, device=None: load_file(path, device="cpu")
        try:
            with _quiet():
                _model = mt.TranscriptionModel.load_model(weights_path=ensure_weights(), device=device)
        finally:
            mt.load_file = load_file
        _model_device = device
        free_gpu_memory()  # the full-precision copy it was built in
    return _model


def release() -> None:
    """Frees the model (0.6 GB, and the GPU memory it worked in) once both stems are done."""
    global _model, _model_device
    _model = _model_device = None
    from .separate import free_gpu_memory

    free_gpu_memory()


def _transcribe(model, wav, instruments: list[str] | None, progress: Callable[[float], None] | None) -> list[tuple[float, float, int]]:
    """(start, end, MIDI pitch) of every note but the drums. A note still open at the end runs to it."""
    from muscriptor.events import NoteEndEvent, NoteStartEvent, ProgressEvent

    found, sounding = [], {}
    with _quiet():
        for event in model.transcribe((wav, SAMPLE_RATE), instruments=instruments):
            if isinstance(event, NoteStartEvent):
                sounding[event.index] = event
            elif isinstance(event, NoteEndEvent):
                start = sounding.pop(event.start_event.index, event.start_event)
                if start.instrument != "drums":
                    found.append((start.start_time, event.end_time, start.pitch))
            elif isinstance(event, ProgressEvent) and progress and event.total:
                progress(event.completed / event.total)
    end = wav.shape[-1] / SAMPLE_RATE
    found += [(s.start_time, end, s.pitch) for s in sounding.values() if s.instrument != "drums"]
    return found


def _set_velocities(notes: list[Note], mono: np.ndarray) -> None:
    """MuScriptor doesn't say how hard a note is played, so it's read from the stem's loudness at its
    start, on the scale the melody and bass lines use."""
    import librosa

    hop = 441
    loud = 20 * np.log10(librosa.feature.rms(y=mono, frame_length=2048, hop_length=hop, center=True)[0] + 1e-9)
    peak = float(np.percentile(loud, 95)) if len(loud) else 0.0
    for n in notes:
        a = min(int(n.start * SAMPLE_RATE / hop), len(loud) - 1)
        b = max(a + 1, int((n.start + min(n.duration, 0.2)) * SAMPLE_RATE / hop))
        level = float(np.mean(loud[a:b]))
        n.velocity = int(40 + 70 * np.clip((level - (peak - 30)) / 30, 0, 1))


def transcribe_instruments(
    audio: np.ndarray,
    progress: Callable[[float], None] | None = None,
    tuning: float = 0.0,
    instruments: list[str] | None = None,
    role: Role = Role.HARMONY,
) -> list[Note]:
    """``audio`` is float32 at 44.1 kHz, stereo (2, samples) or mono, and ``tuning`` how many semitones
    it is off A440. ``instruments`` limits what MuScriptor may write (BASS for the bass stem)."""
    import torch

    from .separate import best_device

    mono = np.ascontiguousarray(to_mono(audio), dtype=np.float32)
    tuned, scale = retune(mono, SAMPLE_RATE, tuning)
    wav = torch.from_numpy(np.ascontiguousarray(tuned, dtype=np.float32))[None]
    device = best_device()
    try:
        found = _transcribe(_load(device), wav, instruments, progress)
    except RuntimeError:
        if device == "cpu":
            raise
        found = _transcribe(_load("cpu"), wav, instruments, progress)  # the GPU can run out of memory
    notes = []
    for start, end, pitch in found:
        start, end = max(start - LAG, 0.0) * scale, max(end - LAG, 0.0) * scale
        if end > start:
            notes.append(Note(int(pitch), start, end - start, role=role))
    notes.sort(key=lambda n: (n.start, n.pitch))
    if notes:
        _set_velocities(notes, mono)
    return notes
