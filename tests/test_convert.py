"""The audio paths end to end on synthetic songs (slow: runs the separation and transcription models)."""

import time

import numpy as np
import pytest
import soundfile

from legatoengine.arrange.pipeline import ArrangeSettings, arrange
from legatoengine.ingest import cache
from legatoengine.ingest.convert import load_song
from legatoengine.models import Note, Role
from legatoengine.synth import render

pytestmark = pytest.mark.slow
SR = 44100


@pytest.fixture(autouse=True)
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")


def band_song(path):
    """Synth lead + bass + chords + noise drums, 12 seconds."""
    melody = [Note(p, i * 0.5, 0.45, 100) for i, p in enumerate([72, 74, 76, 77, 79, 77, 76, 74] * 3)]
    bass = [Note([36, 41, 43, 36][i % 4], i * 1.0, 0.9, 110) for i in range(12)]
    chords = [Note(p, i * 2.0, 1.9, 60) for i in range(6) for p in ([60, 64, 67], [65, 69, 72], [67, 71, 74])[i % 3]]
    mix = render(melody, SR, gain=0.25) [: 12 * SR]
    mix = np.pad(mix, (0, max(0, 12 * SR - len(mix))))
    for part in (bass, chords):
        audio = render(part, SR, gain=0.25)[: 12 * SR]
        mix[: len(audio)] += audio
    rng = np.random.default_rng(0)
    for i in range(24):
        s = int(i * 0.5 * SR)
        hit = 0.3 * rng.standard_normal(2000) * np.exp(-np.arange(2000) / 300)
        mix[s : s + 2000] += hit[: len(mix) - s]
    soundfile.write(path, (mix / np.abs(mix).max() * 0.9).astype(np.float32), SR)


def test_full_song_path(tmp_path):
    path = tmp_path / "band.wav"
    band_song(path)
    stages = []
    song = load_song(path, "full", progress=lambda label, f: stages.append((label, f)))
    assert song.source_kind == "full"
    assert song.title == "band"
    assert len(song.notes) > 20
    bass = [n for n in song.notes if n.role is Role.BASS]
    assert {36, 41, 43} <= {n.pitch for n in bass}  # the bass line comes from the bass stem
    assert song.beats and 60 < song.tempo < 200
    fractions = [f for _, f in stages]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    from legatoengine.ingest import separate, transcribe_multi, transcribe_poly

    loaded = (separate._model, separate._mlx_weights, transcribe_multi._model, transcribe_poly._model)
    assert all(m is None for m in loaded)  # each model is freed once it's done, so they never add up
    script = arrange(song, ArrangeSettings())
    assert {n.role for n in script.notes} == {Role.MELODY, Role.BASS, Role.HARMONY}

    started = time.perf_counter()
    again = load_song(path, "full")
    assert time.perf_counter() - started < 1.0  # from the cache
    assert again.notes == song.notes


def test_full_song_without_the_instrument_model(tmp_path, monkeypatch):
    from legatoengine.ingest import transcribe_multi
    from legatoengine.ingest.separate import ModelDownloadError

    def gated(progress=None):
        raise ModelDownloadError(transcribe_multi.GATED_HELP)

    monkeypatch.setattr(transcribe_multi, "is_ready", lambda: False)
    monkeypatch.setattr(transcribe_multi, "ensure_weights", gated)
    path = tmp_path / "band.wav"
    band_song(path)
    stages = []
    with pytest.warns(RuntimeWarning, match="Hugging Face account"):
        song = load_song(path, "full", progress=lambda label, f: stages.append(label))
    bass = [n for n in song.notes if n.role is Role.BASS]
    assert {36, 41, 43} <= {n.pitch for n in bass}  # SwiftF0 follows the bass line instead
    assert any("couldn't be downloaded" in label for label in stages)
    assert cache.load(song.source_hash, "full") is None  # so the next conversion tries again


def test_piano_path_and_auto_detection(tmp_path):
    truth = [Note(p, 0.5 + i * 0.4, 0.35, 90) for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72] * 2)]
    truth += [Note(p, 7.0, 1.5, 80) for p in (48, 55, 64)]
    path = tmp_path / "piano.wav"
    soundfile.write(path, render(truth, SR), SR)
    song = load_song(path, "piano")
    assert song.source_kind == "piano"
    found = {(n.pitch, round(n.start, 1)) for n in song.notes}
    expected = {(n.pitch, round(n.start, 1)) for n in truth}
    assert len(found & expected) >= 0.8 * len(expected)
    auto = load_song(path, "auto")
    assert auto.source_kind == "piano"
