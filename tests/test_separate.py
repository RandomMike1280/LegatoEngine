"""The separator's chunking, its MLX path with the PyTorch fallback, the MLX port against
PyTorch on a small random model, and the one-time model download, without the real model."""

import hashlib

import numpy as np
import pytest
import torch

from legatoengine.ingest import separate
from legatoengine.ingest.separate import CHUNK, STEMS, ModelDownloadError


class Scaler(torch.nn.Module):
    """Stands in for BS-RoFormer: stem k is the input times k + 1, so stitching mistakes show."""

    calls = 0

    def forward(self, audio):
        assert audio.shape == (1, 2, CHUNK)
        self.calls += 1
        return torch.stack([audio[0] * (k + 1) for k in range(len(STEMS))])[None]


@pytest.fixture
def fake_model(monkeypatch):
    model = Scaler()
    monkeypatch.setattr(separate, "_model", model)
    return model


@pytest.mark.parametrize("length", [1000, CHUNK, CHUNK + 400_000, 2 * CHUNK + 10])
def test_chunks_are_stitched_back_in_place(fake_model, length):
    audio = np.random.default_rng(0).standard_normal((2, length)).astype(np.float32)
    steps = []
    stems = separate.separate(audio, steps.append, device="cpu")
    assert list(stems) == list(STEMS)
    for k, name in enumerate(STEMS):
        assert stems[name].shape == (2, length)
        np.testing.assert_allclose(stems[name], audio * (k + 1), rtol=1e-6)
    assert steps == sorted(steps) and steps[-1] == 1.0


def test_sampled_chunks_are_spread_out_and_not_separated_again(fake_model):
    audio = np.random.default_rng(1).standard_normal((2, 10 * CHUNK + 5)).astype(np.float32)
    assert separate.sample_chunks(audio[:, : 2 * CHUNK]) == [0, 1]
    sample = separate.sample_chunks(audio)
    assert sample == [1, 5, 9]
    done = separate.separate_chunks(audio, sample, device="cpu")
    assert fake_model.calls == 3
    steps = []
    stems = separate.separate(audio, steps.append, device="cpu", done=done)
    assert fake_model.calls == 11
    np.testing.assert_allclose(stems["piano"], audio * 6, rtol=1e-6)
    assert steps[0] > 3 / 11 - 1e-9 and steps == sorted(steps) and steps[-1] == 1.0


@pytest.fixture
def fake_mlx(monkeypatch):
    """MLX stand-in with the same output as Scaler; ``bad`` maps a call number to what goes wrong."""
    calls = []
    bad = {}

    def chunk(part):
        calls.append(len(calls))
        if bad.get(len(calls)) == "raise":
            raise RuntimeError("out of memory")
        stems = np.stack([part * (k + 1) for k in range(len(STEMS))])
        return stems * np.nan if bad.get(len(calls)) == "nan" else stems

    monkeypatch.setattr(separate, "mlx_available", lambda: True)
    monkeypatch.setattr(separate, "_mlx_chunk", chunk)
    return calls, bad


def test_chunks_mlx_spoils_are_separated_by_pytorch(fake_model, fake_mlx):
    calls, bad = fake_mlx
    bad[2] = "nan"
    audio = np.random.default_rng(2).standard_normal((2, 3 * CHUNK + 7)).astype(np.float32)
    steps = []
    stems = separate.separate(audio, steps.append)
    assert len(calls) == 4 and fake_model.calls == 1
    for k, name in enumerate(STEMS):
        np.testing.assert_allclose(stems[name], audio * (k + 1), rtol=1e-6)
    assert steps == sorted(steps) and steps[-1] == 1.0


def test_pytorch_finishes_the_song_when_mlx_fails(fake_model, fake_mlx):
    calls, bad = fake_mlx
    bad[3] = "raise"
    audio = np.random.default_rng(3).standard_normal((2, 5 * CHUNK)).astype(np.float32)
    steps = []
    with pytest.warns(RuntimeWarning, match="PyTorch takes over"):
        stems = separate.separate(audio, steps.append)
    assert len(calls) == 3 and fake_model.calls == 3
    np.testing.assert_allclose(stems["bass"], audio, rtol=1e-6)
    assert steps == sorted(steps) and steps[-1] == 1.0


def test_naming_a_pytorch_device_skips_mlx(fake_model, fake_mlx):
    calls, _ = fake_mlx
    separate.separate(np.zeros((2, 1000), np.float32), device="cpu")
    assert not calls and fake_model.calls == 1


def tiny_model():
    """BS-RoFormer with the real bands, heads and STFT but a narrow width, one layer and two stems."""
    from legatoengine.ingest.bs_roformer import BSRoformer

    torch.manual_seed(0)
    model = BSRoformer(**{**separate.CONFIG, "dim": 32, "depth": 1, "num_stems": 2}).eval()
    with torch.no_grad():  # gains away from 1, so folding them into the weights is tested too
        for name, p in model.named_parameters():
            if name.endswith("gamma"):
                p.uniform_(0.5, 1.5)
    return model


def sdr(ref, est):
    return 10 * np.log10((ref.astype(np.float64) ** 2).sum() / ((ref - est).astype(np.float64) ** 2).sum())


def test_the_mlx_port_matches_pytorch():
    mx = pytest.importorskip("mlx.core")
    from legatoengine.ingest import bs_roformer_mlx

    model = tiny_model()
    rng = np.random.default_rng(4)
    audio = (rng.standard_normal((2, 44100)) * 0.1).astype(np.float32)
    audio[:, 30000:] *= 1e-14  # a near-silent ending, where the band split's clamp matters
    with torch.inference_mode():
        ref = model(torch.from_numpy(audio)[None])[0].numpy()
    weights = bs_roformer_mlx.convert({k: v.numpy() for k, v in model.state_dict().items()})
    for arrays, floor in ((weights, 100), (bs_roformer_mlx.half(weights), 50)):  # measured 122 and 61 dB
        out = np.array(bs_roformer_mlx.separate_chunk({k: mx.array(v) for k, v in arrays.items()}, mx.array(audio)))
        assert out.shape == ref.shape == (2, 2, 44100)
        for k in range(2):
            assert sdr(ref[k], out[k]) > floor


def test_mlx_weights_are_converted_once(tmp_path, monkeypatch):
    pytest.importorskip("mlx.core")
    model = tiny_model()
    loads = []
    monkeypatch.setattr(separate, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(separate, "_load_state", lambda: loads.append(1) or model.state_dict())
    monkeypatch.setattr(separate, "_mlx_weights", None)
    weights = separate._load_mlx_weights()
    assert [p.name for p in tmp_path.iterdir()] == [separate.MLX_FILE]
    assert str(weights["split0"].dtype) == "mlx.core.float32" and str(weights["time0.qkvg"].dtype) == "mlx.core.float16"
    monkeypatch.setattr(separate, "_mlx_weights", None)
    assert set(separate._load_mlx_weights()) == set(weights) and loads == [1]


@pytest.fixture
def mirrors(tmp_path, monkeypatch):
    """A tiny 'checkpoint' served from files, with the module pointed at a temporary models folder."""
    data = bytes(range(256)) * 9000
    good = tmp_path / "good.ckpt"
    good.write_bytes(data)
    bad = tmp_path / "bad.ckpt"
    bad.write_bytes(data[:-1] + b"x")
    monkeypatch.setattr(separate, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(separate, "CHECKPOINT_SIZE", len(data))
    monkeypatch.setattr(separate, "CHECKPOINT_SHA256", hashlib.sha256(data).hexdigest())
    return {"good": good.as_uri(), "bad": bad.as_uri(), "missing": (tmp_path / "missing.ckpt").as_uri(), "data": data}


def test_download_falls_back_to_the_next_mirror(mirrors, monkeypatch):
    monkeypatch.setattr(separate, "CHECKPOINT_URLS", (mirrors["missing"], mirrors["good"]))
    assert not separate.is_downloaded()
    steps = []
    path = separate.ensure_checkpoint(steps.append)
    assert path.read_bytes() == mirrors["data"] and separate.is_downloaded()
    assert steps == sorted(steps) and steps[-1] == 1.0
    assert list(path.parent.iterdir()) == [path]  # no .part left behind
    assert separate.ensure_checkpoint() == path  # and it isn't fetched again


def test_a_damaged_download_is_refused(mirrors, monkeypatch):
    monkeypatch.setattr(separate, "CHECKPOINT_URLS", (mirrors["bad"],))
    with pytest.raises(ModelDownloadError, match="damaged"):
        separate.ensure_checkpoint()
    assert not separate.is_downloaded()
    assert not list((separate.MODELS_DIR).iterdir())


def test_an_unreachable_model_says_so(mirrors, monkeypatch):
    monkeypatch.setattr(separate, "CHECKPOINT_URLS", (mirrors["missing"],))
    with pytest.raises(ModelDownloadError, match="Couldn't download the separation model"):
        separate.ensure_checkpoint()
