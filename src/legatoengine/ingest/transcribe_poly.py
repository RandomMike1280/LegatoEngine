"""Polyphonic transcription with Transkun V2 (Yan and Duan, 2024).

Used on solo piano recordings and, in full songs, on the piano stem (on the piano,
guitar and other stems together when MuScriptor can't be used). Transkun scores every note as a whole, from key down to key up, so a
held note comes out as one press and a re-struck one as two. It runs on the GPU when
there is one: on an M1 Pro, about 8x faster than real time.

It replaced the ByteDance model (Kong et al., 2021), which ran at 2.5x on the CPU only,
heard many false notes in echoey, noisy or phone-quality recordings, and on soft ones
heard held notes struck again. Transkun skips notes in audio that isn't tuned to A440,
so the converter passes the tuning, and the audio is retuned before the model hears it.
"""

from __future__ import annotations

import json
import math
import warnings
from importlib.resources import files
from typing import Callable

import numpy as np

from ..models import Note
from .audio import retune

SAMPLE_RATE = 44100
SUSTAIN = 64  # Transkun reports pedals as notes with negative pitches: -64 sustain, -67 soft

_model = None


def _mel_forward(self, frames):
    """Transkun's MelSpectrum.forward, with the spectrogram made contiguous before the filterbank.
    Without that, the matmul copies the 229-band filterbank once per frame (691 of them) on the
    GPU: 1.2 GB for every 16 s window. The notes come out the same."""
    spectrogram = self.spectrogramExtractor(frames).abs().pow(2)
    if self.toMono and len(spectrogram.shape) >= 4:
        spectrogram = spectrogram.mean(dim=-4, keepdim=True)
    mel = (spectrogram.transpose(-1, -2).contiguous() @ self.freq2mels).transpose(-1, -2)
    if self.log:
        mel = ((mel + self.eps).log() - math.log(self.eps)) / (-math.log(self.eps))
    return mel


def _load(device: str):
    global _model
    if _model is None:
        import types

        import torch

        with warnings.catch_warnings():
            # PyTorch 2.15 deprecates TorchScript, which compiles Transkun's Viterbi decoder on import
            warnings.filterwarnings("ignore", "`torch.jit.script` is deprecated", FutureWarning)
            from transkun.ModelTransformer import ModelConfig, TransKun
            from transkun.Util import MelSpectrum

        weights = files("transkun") / "pretrained"  # 56 MB, inside the package
        conf = ModelConfig()
        conf.__dict__.update(json.loads((weights / "2.0.conf").read_text())["Model"]["config"])
        _model = TransKun(conf=conf)
        _model.load_state_dict(torch.load(str(weights / "2.0.pt"), map_location="cpu", weights_only=True)["state_dict"])
        _model.eval()
        mel = _model.framewiseFeatureExtractor
        if type(mel) is MelSpectrum:
            mel.forward = types.MethodType(_mel_forward, mel)
    return _model.to(device)


def release() -> None:
    """Frees the model and the GPU memory it worked in (about 2.5 GB at its peak)."""
    global _model
    _model = None
    from .separate import free_gpu_memory

    free_gpu_memory()


def _transcribe(model, audio: np.ndarray, device: str, progress: Callable[[float], None] | None) -> list:
    """Transkun's own loop over 16 s windows, reporting progress after each one."""
    import torch

    pad = math.ceil((model.segmentSizeInSecond - model.segmentHopSizeInSecond) * model.fs)
    step = math.ceil(model.segmentHopSizeInSecond * model.fs / model.hopSize) * model.hopSize
    windows = math.ceil((audio.shape[1] + 2 * pad) / step)
    done = 0
    transcribe_frames = model.transcribeFrames

    def counted(*args, **kwargs):
        nonlocal done
        result = transcribe_frames(*args, **kwargs)
        done += 1
        if progress:
            progress(done / windows)
        return result

    model.transcribeFrames = counted
    try:
        with torch.no_grad(), warnings.catch_warnings():
            # Transkun's layers use training-time checkpointing, which warns when there's no training
            warnings.filterwarnings("ignore", "torch.utils.checkpoint", UserWarning)
            warnings.filterwarnings("ignore", "None of the inputs have requires_grad", UserWarning)
            return model.transcribe(torch.from_numpy(np.ascontiguousarray(audio.T)).to(device))
    finally:
        del model.transcribeFrames


def transcribe_polyphonic(
    audio: np.ndarray, progress: Callable[[float], None] | None = None, tuning: float = 0.0
) -> tuple[list[Note], list[tuple[float, float]]]:
    """``audio`` is float32 at 44.1 kHz, stereo (2, samples) or mono, and ``tuning`` how many
    semitones it is off A440. Returns (notes, sustain pedal intervals)."""
    from .separate import best_device

    if audio.ndim == 1:
        audio = np.stack([audio, audio])
    audio, scale = retune(audio, SAMPLE_RATE, tuning)
    device = best_device()
    try:
        events = _transcribe(_load(device), audio, device, progress)
    except RuntimeError:
        if device == "cpu":
            raise
        events = _transcribe(_load("cpu"), audio, "cpu", progress)  # the GPU can run out of memory
    notes = [
        Note(int(e.pitch), float(e.start) * scale, float(e.end - e.start) * scale, int(e.velocity))
        for e in events
        if e.pitch > 0 and e.end > e.start
    ]
    notes.sort(key=lambda n: (n.start, n.pitch))
    pedals = sorted((float(e.start) * scale, float(e.end) * scale) for e in events if e.pitch == -SUSTAIN and e.end > e.start)
    return notes, pedals
