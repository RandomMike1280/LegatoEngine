"""MuScriptor's events becoming notes, and getting its gated weights in place."""

import hashlib
import json

import numpy as np
import pytest

from autopiano.ingest import transcribe_multi
from autopiano.ingest.separate import ModelDownloadError
from autopiano.models import Note, Role
from autopiano.synth import render

SR = 44100


class FakeModel:
    """Yields what MuScriptor would: a guitar note, a drum hit, a progress mark and a note left open."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, instruments=None):
        from muscriptor.events import NoteEndEvent, NoteStartEvent, ProgressEvent

        wav, sample_rate = audio
        self.calls.append((wav.shape, sample_rate, instruments))
        guitar = NoteStartEvent(pitch=64, start_time=1.013, index=0, instrument="acoustic_guitar")
        drum = NoteStartEvent(pitch=36, start_time=1.5, index=1, instrument="drums")
        held = NoteStartEvent(pitch=48, start_time=2.013, index=2, instrument="electric_bass")
        yield ProgressEvent(completed=0, total=2)
        yield guitar
        yield drum
        yield NoteEndEvent(end_time=1.513, start_event=guitar)
        yield NoteEndEvent(end_time=1.6, start_event=drum)
        yield ProgressEvent(completed=1, total=2)
        yield held
        yield ProgressEvent(completed=2, total=2)


@pytest.fixture
def fake(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(transcribe_multi, "_load", lambda device: model)
    return model


def test_events_become_notes(fake):
    audio = np.stack([render([Note(64, 1.0, 0.5, 100), Note(48, 2.0, 1.0, 60)], SR)[: 3 * SR]] * 2)
    progress = []
    notes = transcribe_multi.transcribe_instruments(audio, progress.append, instruments=transcribe_multi.BASS, role=Role.BASS)
    assert [(n.pitch, round(n.start, 3), round(n.duration, 3)) for n in notes] == [(64, 1.0, 0.5), (48, 2.0, round(1.0 - transcribe_multi.LAG, 3))]
    assert all(n.role is Role.BASS for n in notes)  # the drum hit is dropped, the open note runs to the end
    assert all(40 <= n.velocity <= 110 for n in notes)
    assert notes[0].velocity > notes[1].velocity  # the guitar note was played louder
    assert progress == [0.0, 0.5, 1.0]
    (shape, sample_rate, instruments), = fake.calls
    assert shape == (1, 3 * SR) and sample_rate == SR and instruments == transcribe_multi.BASS


def test_notes_are_timed_in_the_original_once_retuned(fake):
    audio = np.zeros((2, 3 * SR), np.float32)
    audio[:, ::100] = 0.1
    notes = transcribe_multi.transcribe_instruments(audio, tuning=0.5)
    scale = 2 ** (-0.5 / 12)  # the model heard it played a little slower
    assert notes[0].start == pytest.approx(1.0 * scale)
    assert fake.calls[0][0][1] == pytest.approx(3 * SR / scale, abs=2)


@pytest.fixture
def weights(tmp_path, monkeypatch):
    """A small stand-in for the 1.2 GB weights file, in a stand-in Hugging Face cache."""
    blob = tmp_path / "hf" / "blob"
    blob.parent.mkdir()
    blob.write_bytes(b"weights" * 1000)
    monkeypatch.setattr(transcribe_multi, "FOLDER", tmp_path / "models" / "MuScriptor-medium")
    monkeypatch.setattr(transcribe_multi, "WEIGHTS_SIZE", blob.stat().st_size)
    monkeypatch.setattr(transcribe_multi, "WEIGHTS_SHA256", hashlib.sha256(blob.read_bytes()).hexdigest())
    return blob


def test_weights_are_linked_from_the_hugging_face_cache(weights, monkeypatch):
    asked = []

    def download(repo_id, filename, revision=None):
        asked.append((repo_id, filename, revision))
        return str(weights)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    assert not transcribe_multi.is_ready()
    path = transcribe_multi.ensure_weights()
    assert transcribe_multi.is_ready()
    assert path.stat().st_ino == weights.stat().st_ino  # a hard link, not a second copy
    assert json.loads((path.parent / "config.json").read_text())["variant"] == "medium"
    assert asked == [(transcribe_multi.REPO, "model.safetensors", transcribe_multi.REVISION)]
    transcribe_multi.ensure_weights()
    assert len(asked) == 1  # already in place


def test_gated_weights_explain_how_to_get_access(weights, monkeypatch):
    import httpx2
    from huggingface_hub.errors import GatedRepoError

    def download(*args, **kwargs):
        raise GatedRepoError("gated", response=httpx2.Response(403, request=httpx2.Request("GET", "https://huggingface.co")))

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    with pytest.raises(ModelDownloadError, match="Hugging Face account"):
        transcribe_multi.ensure_weights()


def test_damaged_weights_are_not_used(weights, monkeypatch):
    weights.write_bytes(b"x" * weights.stat().st_size)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", lambda *a, **k: str(weights))
    with pytest.raises(ModelDownloadError, match="damaged"):
        transcribe_multi.ensure_weights()
    assert not transcribe_multi.is_ready()


@pytest.mark.slow
@pytest.mark.skipif(not transcribe_multi.is_ready(), reason="the MuScriptor weights aren't on this Mac")
def test_muscriptor_follows_a_bass_line_down_to_low_e():
    pitches = [36, 41, 43, 36, 40, 45, 31, 29, 28]
    audio = render([Note(p, 0.2 + i * 0.6, 0.5, 110) for i, p in enumerate(pitches)], SR)
    notes = transcribe_multi.transcribe_instruments(audio, instruments=transcribe_multi.BASS, role=Role.BASS)
    assert [n.pitch for n in notes] == pitches
    assert [round(n.start, 1) for n in notes] == [round(0.2 + i * 0.6, 1) for i in range(len(pitches))]
