"""Splits a full song into instrument stems with BS-RoFormer-SW, a 6-stem band-split RoFormer.

The song goes through the model in 13.35-second chunks, one after another. Overlapping the chunks
would take about twice as long for about 0.4 dB cleaner stems. The weights (699 MB) are
downloaded the first time and checked against their SHA-256.

On Apple Silicon the model runs in MLX at half precision (bs_roformer_mlx.py), about twice as fast
as PyTorch on MPS, from a copy of the weights converted the first time (350 MB). PyTorch separates
any chunk MLX can't."""

from __future__ import annotations

import hashlib
import urllib.request
import warnings
from pathlib import Path
from typing import Callable

import numpy as np

from ..paths import MODELS_DIR

MODEL_NAME = "BS-RoFormer-SW"
SAMPLE_RATE = 44100
STEMS = ("bass", "drums", "other", "vocals", "guitar", "piano")  # the order the model outputs them in
CHUNK = 588800  # samples per pass, as the model was trained

CHECKPOINT_FILE = "BS-Rofo-SW-Fixed.ckpt"
CHECKPOINT_SIZE = 699_412_152
CHECKPOINT_SHA256 = "24e7d35ee9c64415673d3fd33e06a67cac2c103c5df6267ba1576459c775916e"
# Two mirrors of the same file, pinned to a revision (the original uploader's account is gone)
CHECKPOINT_URLS = (
    "https://huggingface.co/FractalSurfer/BS-RoFormer-SW-6stem/resolve/2b98254b19bdab07ce225d884ec4aa9dd8aafce1/BS-Rofo-SW-Fixed.ckpt",
    "https://huggingface.co/enerjazzer/BS-ROFO-SW-Fixed/resolve/a443a2985534b3bc815ef54a5d446c6a0390f974/BS-Rofo-SW-Fixed.ckpt",
)
MLX_FILE = "BS-Rofo-SW-Fixed.mlx-fp16.safetensors"  # converted from the checkpoint on first use
# The checkpoint's own config (BS-Rofo-SW-Fixed.yaml, "model")
CONFIG = dict(
    dim=256,
    depth=12,
    stereo=True,
    num_stems=6,
    time_transformer_depth=1,
    freq_transformer_depth=1,
    linear_transformer_depth=0,
    freqs_per_bands=(2,) * 24 + (4,) * 12 + (12,) * 8 + (24,) * 8 + (48,) * 8 + (128, 129),
    dim_head=64,
    heads=8,
    attn_dropout=0.1,
    ff_dropout=0.1,
    flash_attn=True,
    dim_freqs_in=1025,
    stft_n_fft=2048,
    stft_hop_length=512,
    stft_win_length=2048,
    stft_normalized=False,
    mask_estimator_depth=2,
    multi_stft_resolution_loss_weight=1.0,
    multi_stft_resolutions_window_sizes=(4096, 2048, 1024, 512, 256),
    multi_stft_hop_size=147,
    multi_stft_normalized=False,
    mlp_expansion_factor=4,
    use_torch_checkpoint=False,
    skip_connection=False,
)

_model = None
_mlx_weights = None


class ModelDownloadError(Exception):
    """The separation model couldn't be downloaded. The message is safe to show the user."""


def best_device() -> str:
    """The PyTorch device: the transcription models use it too."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def mlx_available() -> bool:
    try:
        import mlx.core as mx
    except ImportError:
        return False
    return mx.metal.is_available()


def free_gpu_memory() -> None:
    """Hands the memory the models freed back to the system (on a Mac, PyTorch's goes a second
    or two later), so each model can have what the one before it used."""
    import gc

    import torch

    gc.collect()
    if mlx_available():
        import mlx.core as mx

        mx.clear_cache()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def release() -> None:
    """Frees the separation model (0.35 GB in MLX, 0.7 GB in PyTorch) once the stems are out."""
    global _model, _mlx_weights
    _model = _mlx_weights = None
    free_gpu_memory()


def checkpoint_path() -> Path:
    return MODELS_DIR / CHECKPOINT_FILE


def is_downloaded() -> bool:
    path = checkpoint_path()
    return path.exists() and path.stat().st_size == CHECKPOINT_SIZE


def ensure_checkpoint(progress: Callable[[float], None] | None = None) -> Path:
    """Downloads the weights unless they're already there, trying each mirror in turn."""
    path = checkpoint_path()
    if not is_downloaded():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        shown = 0.0
        error = ""
        try:
            for url in CHECKPOINT_URLS:
                digest = hashlib.sha256()
                try:
                    with urllib.request.urlopen(url, timeout=60) as response, open(part, "wb") as out:
                        done = 0
                        while block := response.read(1 << 20):
                            out.write(block)
                            digest.update(block)
                            done += len(block)
                            if progress and done / CHECKPOINT_SIZE > shown:
                                shown = min(done / CHECKPOINT_SIZE, 1.0)
                                progress(shown)
                except OSError as e:
                    error = f"Couldn't download the separation model (699 MB): {e}"
                    continue
                if digest.hexdigest() == CHECKPOINT_SHA256:
                    part.replace(path)
                    break
                error = "The separation model download was damaged. Try again."
            else:
                raise ModelDownloadError(error)
        finally:
            part.unlink(missing_ok=True)
    if progress:
        progress(1.0)
    return path


def _load_state() -> dict:
    import torch

    state = torch.load(ensure_checkpoint(), map_location="cpu", weights_only=True)
    return state.get("state_dict", state)


def _load_model():
    global _model
    if _model is None:
        from .bs_roformer import BSRoformer

        model = BSRoformer(**CONFIG)
        model.load_state_dict(_load_state())
        _model = model.eval()
    return _model


def _load_mlx_weights() -> dict:
    """The fp16 weights for MLX, converted from the checkpoint the first time (a few seconds)."""
    global _mlx_weights
    if _mlx_weights is None:
        import mlx.core as mx

        from . import bs_roformer_mlx

        path = MODELS_DIR / MLX_FILE
        if not path.exists():
            arrays = bs_roformer_mlx.half(bs_roformer_mlx.convert({k: v.numpy() for k, v in _load_state().items()}))
            part = path.with_name("converting-" + path.name)
            mx.save_safetensors(str(part), {k: mx.array(v) for k, v in arrays.items()})
            part.replace(path)
        _mlx_weights = mx.load(str(path))
    return _mlx_weights


def chunk_count(audio: np.ndarray) -> int:
    return max(1, -(-audio.shape[1] // CHUNK))


def sample_chunks(audio: np.ndarray, count: int = 3) -> list[int]:
    """``count`` chunks spread through the song (all of them in a short one)."""
    total = chunk_count(audio)
    if total <= count:
        return list(range(total))
    return [int((i + 0.5) * total / count) for i in range(count)]


def separate(
    audio: np.ndarray,
    progress: Callable[[float], None] | None = None,
    device: str | None = None,
    done: dict[int, np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """``audio`` is stereo float32 (2, samples) at 44.1 kHz. Returns stereo stems by name.
    ``done`` holds chunks already separated by separate_chunks, which aren't separated again.
    ``device`` names a PyTorch device to use instead of MLX."""
    chunks = dict(done or {})
    total = chunk_count(audio)
    todo = [i for i in range(total) if i not in chunks]
    if todo:
        before = len(chunks)
        step = (lambda f: progress((before + f * len(todo)) / total)) if progress else None
        chunks.update(separate_chunks(audio, todo, step, device))
    if progress:
        progress(1.0)
    return joined(chunks)


def joined(chunks: dict[int, np.ndarray]) -> dict[str, np.ndarray]:
    """Stems by name from separated chunks, in order: the whole song once every chunk is there."""
    out = np.concatenate([chunks[i] for i in sorted(chunks)], axis=2)
    return {name: out[k] for k, name in enumerate(STEMS)}


def separate_chunks(
    audio: np.ndarray, indices: list[int], progress: Callable[[float], None] | None = None, device: str | None = None
) -> dict[int, np.ndarray]:
    """The model's output, (stems, 2, samples), for the chunks numbered ``indices``: from MLX where
    it can, unless a PyTorch ``device`` is named, and from PyTorch for the rest."""
    results = {}
    if device is None and mlx_available():
        try:
            _run_mlx(audio, indices, results, progress)
        except Exception as e:  # out of GPU memory, say: PyTorch separates what's left
            warnings.warn(f"MLX separation failed, so PyTorch takes over: {e!r}", RuntimeWarning)
    todo = [i for i in indices if i not in results]
    if todo:
        before = len(results)
        step = (lambda f: progress((before + f * len(todo)) / len(indices))) if progress else None
        device = device or best_device()
        try:
            results.update(_run(audio, todo, device, step))
        except RuntimeError:
            if device == "cpu":
                raise
            results.update(_run(audio, todo, "cpu", step))
    return results


def _chunk(audio: np.ndarray, index: int) -> tuple[np.ndarray, int]:
    """Chunk ``index`` as float32 (2, CHUNK), and how many of its samples are the song's. The last
    chunk is padded with its own mirror image when that's long enough, else with silence."""
    part = np.ascontiguousarray(audio[:, index * CHUNK : (index + 1) * CHUNK], dtype=np.float32)
    n = part.shape[1]
    if n < CHUNK:
        part = np.pad(part, ((0, 0), (0, CHUNK - n)), mode="reflect" if n > CHUNK // 2 else "constant")
    return part, n


def _mlx_chunk(part: np.ndarray) -> np.ndarray:
    import mlx.core as mx

    from . import bs_roformer_mlx

    return np.array(bs_roformer_mlx.separate_chunk(_load_mlx_weights(), mx.array(part)))


def _run_mlx(
    audio: np.ndarray, indices: list[int], results: dict[int, np.ndarray], progress: Callable[[float], None] | None
) -> None:
    """Adds each chunk to ``results`` as it's separated, leaving out any that came out with NaNs or
    infinities (fp16 can overflow, though no song has yet)."""
    import mlx.core as mx

    # with no cache, MLX hands each buffer back as soon as it's done with it: 1.1 GB less at the
    # peak, and no slower
    previous = mx.set_cache_limit(0)
    try:
        for index in indices:
            part, n = _chunk(audio, index)
            stems = _mlx_chunk(part)[:, :, :n]
            if np.isfinite(stems).all():
                results[index] = stems
            if progress:
                progress(min(len(results) / len(indices), 0.99))
    finally:
        mx.set_cache_limit(previous)
        mx.clear_cache()  # hands the GPU memory back to the transcription models


def _run(audio: np.ndarray, indices: list[int], device: str, progress: Callable[[float], None] | None) -> dict[int, np.ndarray]:
    import torch

    model = _load_model().to(device)
    results = {}
    with torch.inference_mode(), warnings.catch_warnings():
        # the vendored attention still calls this old (working) PyTorch API on every chunk
        warnings.filterwarnings("ignore", r"`torch.backends.cuda.sdp_kernel\(\)` is deprecated", FutureWarning)
        for i, index in enumerate(indices):
            part, n = _chunk(audio, index)
            results[index] = model(torch.from_numpy(part)[None].to(device))[0, :, :, :n].float().cpu().numpy()
            if progress:
                progress(min((i + 1) / len(indices), 0.99))
    return results
