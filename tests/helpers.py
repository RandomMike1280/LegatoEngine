"""Builds small MIDI files for tests."""

from __future__ import annotations

from pathlib import Path

import mido

TPB = 480


def write_midi(path: Path, tracks: list[dict], bpm: float = 120.0, tempo_changes=()) -> Path:
    """tracks: [{"name": str, "program": int|None, "channel": int, "notes": [(pitch, start_beat, len_beats, vel)],
    "pedal": [(start_beat, end_beat)]}]"""
    mid = mido.MidiFile(type=1, ticks_per_beat=TPB)
    meta = mido.MidiTrack()
    events = [(0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))]
    for beat, new_bpm in tempo_changes:
        events.append((int(beat * TPB), mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(new_bpm))))
    _append(meta, events)
    mid.tracks.append(meta)
    for spec in tracks:
        track = mido.MidiTrack()
        ch = spec.get("channel", 0)
        events = [(0, mido.MetaMessage("track_name", name=spec.get("name", "")))]
        if spec.get("program") is not None:
            events.append((0, mido.Message("program_change", channel=ch, program=spec["program"])))
        for pitch, start, length, vel in spec.get("notes", []):
            events.append((int(start * TPB), mido.Message("note_on", channel=ch, note=pitch, velocity=vel)))
            events.append((int((start + length) * TPB), mido.Message("note_off", channel=ch, note=pitch, velocity=0)))
        for start, end in spec.get("pedal", []):
            events.append((int(start * TPB), mido.Message("control_change", channel=ch, control=64, value=127)))
            events.append((int(end * TPB), mido.Message("control_change", channel=ch, control=64, value=0)))
        _append(track, events)
        mid.tracks.append(track)
    mid.save(path)
    return path


def _append(track: mido.MidiTrack, events) -> None:
    # note_off before note_on at the same tick, like real sequencers
    events.sort(key=lambda e: (e[0], 0 if e[1].type == "note_off" else 1))
    last = 0
    for tick, msg in events:
        track.append(msg.copy(time=tick - last))
        last = tick


def scale_song(tonic: int = 60) -> list[dict]:
    """A I-IV-V-I progression with a scale melody on top, in the major key of ``tonic``."""
    melody, chords, bass = [], [], []
    steps = [0, 2, 4, 5, 7, 9, 11, 12]
    for i, step in enumerate(steps * 2):
        melody.append((tonic + 12 + step, i * 0.5, 0.5, 90))
    for bar, root in enumerate([0, 5, 7, 0]):
        start = bar * 2
        for interval in (0, 4, 7):
            chords.append((tonic + root + interval, start, 2, 60))
        bass.append((tonic - 24 + root, start, 2, 80))
    return [
        {"name": "Melody", "notes": melody},
        {"name": "Chords", "program": 0, "notes": chords},
        {"name": "Bass", "program": 33, "channel": 1, "notes": bass},
    ]
