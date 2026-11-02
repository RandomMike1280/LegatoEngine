import shutil
import subprocess

import numpy as np
import pytest
import soundfile

from legatoengine.ingest.audio import load_audio, resample, retune, tuning_offset
from legatoengine.ingest.transcribe_mono import BASS, VOCALS, segment_notes
from legatoengine.models import Note, Role
from legatoengine.synth import render

FT = 0.01  # 10 ms frames
SR = 44100


def detuned(audio: np.ndarray, sample_rate: int, semitones: float) -> np.ndarray:
    """``audio`` played ``semitones`` sharp (and a little faster), like an old recording."""
    return resample(audio, sample_rate, sample_rate * 2 ** (-semitones / 12))


def curve(*parts):
    """parts: (midi pitch or None for silence, seconds) -> (midi, voiced)"""
    midi, voiced = [], []
    for pitch, seconds in parts:
        n = int(round(seconds / FT))
        midi += [pitch if pitch is not None else 0.0] * n
        voiced += [pitch is not None] * n
    return np.array(midi, float), np.array(voiced)


def test_steps_become_notes():
    midi, voiced = curve((60, 0.5), (62, 0.5), (64, 0.5))
    notes = segment_notes(midi, voiced, FT, VOCALS)
    assert [n.pitch for n in notes] == [60, 62, 64]
    assert [n.start for n in notes] == pytest.approx([0.0, 0.5, 1.0], abs=0.03)


def test_vibrato_stays_one_note():
    t = np.arange(100) * FT
    midi = 67 + 0.6 * np.sin(2 * np.pi * 5.5 * t)
    notes = segment_notes(midi, np.ones(100, bool), FT, VOCALS)
    assert [n.pitch for n in notes] == [67]
    assert notes[0].duration == pytest.approx(1.0)


def test_onset_splits_a_repeated_pitch():
    midi, voiced = curve((65, 1.0))
    loud = np.full(len(midi), -12.0)
    loud[46:50] = -30.0  # the dip between two sung syllables
    notes = segment_notes(midi, voiced, FT, VOCALS, onsets=[50], loudness=loud)
    assert [(n.pitch, round(n.start, 2)) for n in notes] == [(65, 0.0), (65, 0.5)]


def test_onset_without_a_loudness_dip_does_not_split():
    midi, voiced = curve((65, 1.0))
    notes = segment_notes(midi, voiced, FT, VOCALS, onsets=[50], loudness=np.full(len(midi), -12.0))
    assert [n.pitch for n in notes] == [65]


def test_silence_separates_notes():
    midi, voiced = curve((60, 0.3), (None, 0.1), (60, 0.3))
    assert len(segment_notes(midi, voiced, FT, VOCALS)) == 2


def test_short_wobble_is_ignored_and_blips_are_dropped():
    midi, voiced = curve((60, 0.4), (70, 0.03), (60, 0.4), (72, 0.05))
    notes = segment_notes(midi, voiced, FT, VOCALS)
    assert [n.pitch for n in notes] == [60]


def test_loudness_sets_velocity():
    midi, voiced = curve((60, 0.5), (None, 0.2), (62, 0.5))
    loud = np.where(np.arange(len(midi)) < 60, -10.0, -35.0)
    quiet_second = segment_notes(midi, voiced, FT, VOCALS, loudness=loud)
    assert quiet_second[0].velocity > quiet_second[1].velocity


def test_tuning_is_measured():
    chords = [Note(p, i * 0.6, 0.55, 90) for i in range(6) for p in ([60, 64, 67], [57, 60, 64], [65, 69, 72])[i % 3]]
    audio = render(chords, 22050)
    assert tuning_offset(audio, 22050) == pytest.approx(0.0, abs=0.05)
    assert tuning_offset(detuned(audio, 22050, 0.4), 22050) == pytest.approx(0.4, abs=0.05)
    assert tuning_offset(detuned(audio, 22050, -0.3), 22050) == pytest.approx(-0.3, abs=0.05)
    assert tuning_offset(np.zeros(22050, np.float32), 22050) == 0.0


def test_retune_brings_audio_back_to_a440_and_says_how_to_fix_times():
    audio = render([Note(69, 0.2, 2.0, 100)], 22050)
    sharp = detuned(audio, 22050, 0.35)
    fixed, factor = retune(sharp, 22050, 0.35)
    assert tuning_offset(fixed, 22050) == pytest.approx(0.0, abs=0.04)
    assert factor == pytest.approx(2 ** (-0.35 / 12))
    # the sharp copy is shorter; retuned and scaled by the factor, times match it again
    assert len(fixed) * factor == pytest.approx(len(sharp), rel=0.001)
    assert retune(audio, 22050, 0.03) == (audio, 1.0)  # close enough to leave alone


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_reads_m4a_through_ffmpeg(tmp_path):
    wav = tmp_path / "tone.wav"
    soundfile.write(wav, render([Note(69, 0, 1.0, 100)], 44100), 44100)
    m4a = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), str(m4a)], check=True)
    audio = load_audio(m4a, 44100)
    assert audio.shape[0] == 2
    assert abs(audio.shape[1] / 44100 - 1.12) < 0.1


# ---- the real models (slow: a few seconds each, downloads on first run)


def onset_f1(found: list[Note], truth: list[Note], tolerance=0.05) -> float:
    unmatched = list(truth)
    hits = 0
    for n in found:
        match = next((t for t in unmatched if t.pitch == n.pitch and abs(t.start - n.start) <= tolerance), None)
        if match:
            hits += 1
            unmatched.remove(match)
    if not found or not truth:
        return 0.0
    precision, recall = hits / len(found), hits / len(truth)
    return 2 * precision * recall / (precision + recall) if hits else 0.0


@pytest.mark.slow
def test_piano_model_hears_rendered_notes():
    from legatoengine.ingest.transcribe_poly import transcribe_polyphonic

    truth = [Note(p, i * 0.4, 0.35, 90) for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72])]
    truth += [Note(p, 3.6, 1.0, 80) for p in (48, 55, 64)]
    audio = render(truth, SR)
    found, _ = transcribe_polyphonic(audio)
    assert onset_f1(found, truth) >= 0.8


@pytest.mark.slow
def test_piano_model_hears_out_of_tune_audio_once_told_the_tuning():
    from legatoengine.ingest.transcribe_poly import transcribe_polyphonic

    truth = [Note(p, 0.3 + i * 0.4, 0.35, 90) for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72, 74, 76])]
    truth += [Note(p, 4.5, 1.0, 80) for p in (48, 55, 64)]
    sharp = detuned(render(truth, SR), SR, 0.4)
    factor = 2 ** (-0.4 / 12)  # the sharp copy also plays a little faster
    expected = [n.copy(start=n.start * factor) for n in truth]
    found, _ = transcribe_polyphonic(sharp, tuning=tuning_offset(sharp, SR))
    assert onset_f1(found, expected) >= 0.9


@pytest.mark.slow
def test_piano_model_keeps_held_notes_whole_and_real_repeats_apart():
    from legatoengine.ingest.transcribe_poly import transcribe_polyphonic

    beat = 0.3
    held = Note(48, 0.5, 8 * beat, 90)
    line = [Note(p, 0.5 + i * beat, beat, 75) for i, p in enumerate([64, 67, 72, 67, 64, 67, 72, 76])]
    repeats = [Note(69, 3.5 + i * beat, beat, 80) for i in range(6)]
    chords = [Note(p, 5.6 + i * beat, beat, 75) for i in range(4) for p in (60, 64, 67)]
    softer = [Note(62, 7.1 + i * 2 * beat, 2 * beat, v) for i, v in enumerate([90, 70, 70])]
    found, _ = transcribe_polyphonic(render([held, *line, *repeats, *chords, *softer], SR))

    def presses(pitch, lo, hi):
        return sum(1 for n in found if n.pitch == pitch and lo <= n.start < hi)

    assert presses(48, 0, 3.4) == 1
    assert presses(69, 3.4, 5.5) == 6
    assert [presses(p, 5.5, 7.0) for p in (60, 64, 67)] == [4, 4, 4]
    assert presses(62, 7.0, 9.0) == 3


def sing(pitches: list[int], sharp: float = 0.0, sr: int = 16000) -> np.ndarray:
    """A voice with vibrato, 0.4 s per pitch, ``sharp`` semitones above A440."""
    audio = []
    for p in pitches:
        t = np.arange(int(0.4 * sr)) / sr
        f = 440 * 2 ** ((p + sharp - 69) / 12) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * t))
        phase = 2 * np.pi * np.cumsum(f) / sr
        voice = sum(np.sin(k * phase) / k for k in range(1, 6)) * np.minimum(1, 20 * t) * np.minimum(1, 20 * (0.4 - t))
        audio.append(0.3 * voice)
    return np.concatenate(audio).astype(np.float32)


@pytest.mark.slow
def test_line_follows_a_sung_line():
    from legatoengine.ingest.transcribe_mono import transcribe_line

    pitches = [69, 71, 72, 74, 76, 74, 72, 71]
    notes = transcribe_line(sing(pitches), VOCALS, Role.MELODY)
    assert [n.pitch for n in notes] == pitches
    assert all(n.role is Role.MELODY for n in notes)


@pytest.mark.slow
def test_line_is_heard_in_tune_once_told_the_tuning():
    from legatoengine.ingest.transcribe_mono import transcribe_line

    pitches = [69, 71, 72, 74, 76, 74, 72, 71]
    assert [n.pitch for n in transcribe_line(sing(pitches, sharp=0.45), VOCALS, Role.MELODY, tuning=0.45)] == pitches


@pytest.mark.slow
def test_a_quiet_line_is_heard_the_same():
    from legatoengine.ingest.transcribe_mono import transcribe_line

    pitches = [69, 71, 72, 74, 76, 74, 72, 71]
    assert [n.pitch for n in transcribe_line(sing(pitches) * 0.002, VOCALS, Role.MELODY)] == pitches  # about -60 dB


@pytest.mark.slow
def test_line_follows_a_bass_line_down_to_low_e():
    from legatoengine.ingest.transcribe_mono import transcribe_line

    pitches = [36, 41, 43, 36, 40, 45, 31, 29, 28]  # F1 and E1 are below SwiftF0's own range
    audio = render([Note(p, 0.2 + i * 0.6, 0.5, 110) for i, p in enumerate(pitches)], 16000)
    notes = transcribe_line(audio, BASS, Role.BASS)
    assert [n.pitch for n in notes] == pitches
    assert all(n.role is Role.BASS for n in notes)


def test_the_double_speed_pass_only_fills_in_low_notes(monkeypatch):
    """Frames the normal pass hears keep its pitch; frames it can't hear are taken from the
    double-speed pass, but only below its floor."""
    from swift_f0 import PitchResult

    from legatoengine.ingest import transcribe_mono

    n = 100  # 16 ms frames over 1.6 s; played twice as fast, the same audio fills half as many
    normal_hz = np.r_[np.full(40, 110.0), np.zeros(60)]
    normal_conf = np.r_[np.ones(40), np.zeros(60)]
    fast_hz = np.r_[np.full(20, 2 * 55.0), np.full(15, 2 * 41.2), np.full(15, 2 * 60.0)]  # as heard sped up
    calls = []

    class Fake:
        def detect(self, audio, sample_rate, fmin=None, fmax=None):
            calls.append((sample_rate, fmin, fmax))
            if sample_rate == 16000:
                return PitchResult(np.arange(n) * 0.016, normal_hz, normal_conf, np.zeros(n))
            return PitchResult(np.arange(n // 2) * 0.016, fast_hz, np.ones(n // 2), np.zeros(n // 2))

    monkeypatch.setattr(transcribe_mono, "_swift_f0", lambda: Fake())
    audio = np.full(n * 256, 0.5, np.float32)
    midi, voiced, _ = transcribe_mono.pitch_track(audio, BASS)
    t = np.arange(len(midi)) * BASS.hop / 16000
    hz = 440 * 2 ** ((midi - 69) / 12)
    assert voiced[(t > 0.05) & (t < 1.08)].all()
    assert np.allclose(hz[(t > 0.05) & (t < 0.6)], 110)  # heard normally: the fast pass's 55 Hz is ignored
    assert np.allclose(hz[(t > 0.7) & (t < 1.08)], 41.2)  # E1, below SwiftF0's floor
    assert not voiced[(t > 1.17) & (t < 1.55)].any()  # 60 Hz the normal pass couldn't hear stays unheard
    assert calls == [(16000, 46.875, 330), (32000, 65.4, 660)]

    calls.clear()
    transcribe_mono.pitch_track(audio, VOCALS)
    assert [c[0] for c in calls] == [16000]  # singing never goes that low
