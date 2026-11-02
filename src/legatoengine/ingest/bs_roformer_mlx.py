"""BS-RoFormer-SW in MLX: our port of the PyTorch model in bs_roformer/, for inference on Apple
Silicon, where it runs about twice as fast in fp16 as PyTorch does on MPS.

convert() turns the PyTorch state dict into this port's layout: linear layers transposed, each
RMSNorm gain folded into the weights that follow it, and bands of equal width stacked, so each
group of bands is one batched matmul instead of one small matmul per band."""

from __future__ import annotations

import math

import mlx.core as mx
import numpy as np

from .separate import CONFIG

HEADS, DIM_HEAD = CONFIG["heads"], CONFIG["dim_head"]
INNER = HEADS * DIM_HEAD
BANDS = CONFIG["freqs_per_bands"]
N_FFT, HOP = CONFIG["stft_n_fft"], CONFIG["stft_hop_length"]
EPS = 1e-24  # F.normalize clamps the norm at 1e-12, so its square at 1e-24
WINDOW = mx.array(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT), dtype=mx.float32)  # periodic Hann


def _groups() -> list[tuple[int, int, int]]:
    """Runs of bands with the same width: (first band, band count, inputs per band)."""
    runs, i = [], 0
    while i < len(BANDS):
        j = i
        while j < len(BANDS) and BANDS[j] == BANDS[i]:
            j += 1
        runs.append((i, j - i, 4 * BANDS[i]))  # 2 channels x (real, imag) per frequency
        i = j
    return runs


GROUPS = _groups()


def convert(state: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The PyTorch state dict (as numpy) in this port's layout, float32. Every tensor but the
    rotary frequency buffers (theta 10000, which mx.fast.rope recomputes) is used exactly once."""
    used = set()

    def get(key):
        used.add(key)
        return state[key]

    depth = sum(1 for k in state if k.endswith(".0.layers.0.0.norm.gamma"))
    stems = sum(1 for k in state if k.endswith(".to_freqs.0.0.0.weight"))
    w = {}
    for i in range(depth):
        for j, axis in enumerate(("time", "freq")):
            p, q = f"layers.{i}.{j}.layers.0.", f"{axis}{i}."
            gain = get(p + "0.norm.gamma")[:, None]
            w[q + "qkvg"] = gain * np.concatenate([get(p + "0.to_qkv.weight"), get(p + "0.to_gates.weight")]).T
            w[q + "gates_b"] = get(p + "0.to_gates.bias")
            w[q + "out"] = get(p + "0.to_out.0.weight").T
            w[q + "ff1"] = get(p + "1.net.0.gamma")[:, None] * get(p + "1.net.1.weight").T
            w[q + "ff1_b"] = get(p + "1.net.1.bias")
            w[q + "ff2"] = get(p + "1.net.4.weight").T
            w[q + "ff2_b"] = get(p + "1.net.4.bias")
    for start, count, _ in GROUPS:
        f = "band_split.to_features.{}."
        bands = range(start, start + count)
        w[f"split{start}"] = np.stack([get(f.format(k) + "0.gamma")[:, None] * get(f.format(k) + "1.weight").T for k in bands])
        w[f"split{start}_b"] = np.stack([get(f.format(k) + "1.bias") for k in bands])[:, None]
    gain = get("final_norm.gamma")[:, None]
    for n in range(stems):
        f = f"mask_estimators.{n}.to_freqs.{{}}.0."
        w[f"mask{n}.in"] = np.stack([gain * get(f.format(k) + "0.weight").T for k in range(len(BANDS))])
        w[f"mask{n}.in_b"] = np.stack([get(f.format(k) + "0.bias") for k in range(len(BANDS))])[:, None]
        for start, count, _ in GROUPS:
            bands = range(start, start + count)
            w[f"mask{n}.out{start}"] = np.stack([get(f.format(k) + "2.weight").T for k in bands])
            w[f"mask{n}.out{start}_b"] = np.stack([get(f.format(k) + "2.bias") for k in bands])[:, None]
    left = {k for k in state if k not in used and not k.endswith("rotary_embed.freqs")}
    assert not left, f"weights the port doesn't use: {sorted(left)[:5]}"
    return {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in w.items()}


def half(w: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """fp16 weights, except the band split's, which works on the quietest bands (see masks)."""
    return {k: v if k.startswith("split") else v.astype(np.float16) for k, v in w.items()}


def _norm(x: mx.array) -> mx.array:
    """RMSNorm without its gain, which convert() folded into the next weights."""
    return mx.fast.rms_norm(x, None, EPS / x.shape[-1])


def _split_norm(x: mx.array) -> mx.array:
    """The band split's RMSNorm exactly as F.normalize does it: near-silent bands have norms at or
    below its 1e-12 clamp, where rms_norm's smooth eps would scale them differently."""
    return x * (math.sqrt(x.shape[-1]) / mx.maximum(mx.sqrt((x * x).sum(axis=-1, keepdims=True)), 1e-12))


def _rope(x: mx.array) -> mx.array:
    # rotary_embedding_torch rotates interleaved pairs, which MLX calls "traditional"
    return mx.fast.rope(x, DIM_HEAD, traditional=True, base=10000.0, scale=1.0, offset=0)


def _transformer(w: dict[str, mx.array], q: str, x: mx.array) -> mx.array:
    """One residual attention + feed-forward block over the sequences in x (batch, length, dim)."""
    b, n, _ = x.shape
    h = _norm(x) @ w[q + "qkvg"]
    qkv = h[..., : 3 * INNER].reshape(b, n, 3, HEADS, DIM_HEAD).transpose(2, 0, 3, 1, 4)
    out = mx.fast.scaled_dot_product_attention(_rope(qkv[0]), _rope(qkv[1]), qkv[2], scale=DIM_HEAD**-0.5)
    gates = mx.sigmoid(h[..., 3 * INNER :] + w[q + "gates_b"])
    out = (out * gates.transpose(0, 2, 1)[..., None]).transpose(0, 2, 1, 3).reshape(b, n, INNER)
    x = x + out @ w[q + "out"]
    h = _norm(x) @ w[q + "ff1"] + w[q + "ff1_b"]
    h = h * (0.5 * (1 + mx.erf(h * (1 / math.sqrt(2)))))  # exact GELU
    return x + h @ w[q + "ff2"] + w[q + "ff2_b"]


def masks(w: dict[str, mx.array], x: mx.array) -> mx.array:
    """The network: x (frames, 4100) float32 spectrogram features -> (stems, frames, 4100) complex
    masks as interleaved (real, imag), in the dtype of the transformer weights."""
    frames = x.shape[0]
    depth = sum(1 for k in w if k.startswith("time") and k.endswith(".qkvg"))
    stems = sum(1 for k in w if k.startswith("mask") and k.endswith(".in"))
    feats, offset = [], 0
    for start, count, width in GROUPS:  # always fp32: fp16 would flush the quietest bands to zero
        part = x[:, offset : offset + count * width].reshape(frames, count, width).transpose(1, 0, 2)
        feats.append(_split_norm(part) @ w[f"split{start}"] + w[f"split{start}_b"])
        offset += count * width
    x = mx.concatenate(feats).astype(w["time0.qkvg"].dtype)  # (bands, frames, dim)
    for i in range(depth):
        x = _transformer(w, f"time{i}.", x)  # each band along time
        x = _transformer(w, f"freq{i}.", x.transpose(1, 0, 2)).transpose(1, 0, 2)  # each frame across bands
    x = _norm(x)  # final_norm, its gain folded into the mask estimators
    out = []
    for n in range(stems):
        h = mx.tanh(x @ w[f"mask{n}.in"] + w[f"mask{n}.in_b"])  # (bands, frames, hidden)
        parts = []
        for start, count, width in GROUPS:
            y = h[start : start + count] @ w[f"mask{n}.out{start}"] + w[f"mask{n}.out{start}_b"]
            y = y[..., :width] * mx.sigmoid(y[..., width:])  # GLU
            parts.append(y.transpose(1, 0, 2).reshape(frames, count * width))
        out.append(mx.concatenate(parts, axis=-1))
    return mx.stack(out)


def separate_chunk(w: dict[str, mx.array], audio: mx.array) -> mx.array:
    """audio (2, samples) float32 -> stems (stems, 2, samples) float32, like BSRoformer.forward."""
    length = audio.shape[-1]
    # on the CPU (6 ms a chunk): the GPU FFT's rounding noise in near-silent bins is up to 1e-4, and
    # the band split normalises those bins up to full scale, which shifts every stem a little
    spec = mx.fft.stft(audio, n_fft=N_FFT, hop_length=HOP, window=WINDOW, center=True, pad_mode="reflect", stream=mx.cpu)
    frames = spec.shape[-1]  # spec is (2, freqs, frames)
    feats = mx.stack([mx.real(spec), mx.imag(spec)], axis=-1).transpose(2, 1, 0, 3).reshape(frames, -1)  # 't (f s c)'
    m = masks(w, feats).astype(mx.float32)
    m = m.reshape(m.shape[0], frames, -1, 2, 2)  # (stems, frames, freqs, channel, real/imag)
    m = (m[..., 0] + 1j * m[..., 1]).transpose(0, 3, 2, 1)  # (stems, channel, freqs, frames)
    dc = mx.concatenate([mx.zeros((1, 1)), mx.ones((spec.shape[1] - 1, 1))])  # the model zeroes the DC bin
    return mx.fft.istft(spec * m * dc, n_fft=N_FFT, hop_length=HOP, window=WINDOW, center=True, length=length)
