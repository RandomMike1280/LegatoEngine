"""Reads MIDI files into raw notes, with a guess at which part is the melody and bass."""

from __future__ import annotations

import bisect
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import mido

from ..models import Note, Role, Song

DRUM_CHANNEL = 9
MELODY_WORDS = ("vocal", "voice", "vox", "melody", "lead", "sing", "lyric", "solo")
BASS_WORDS = ("bass",)
DEFAULT_TEMPO = 500_000  # microseconds per beat (120 BPM)


class TempoMap:
    def __init__(self, ticks_per_beat: int, changes: list[tuple[int, int]]):
        self.ticks_per_beat = ticks_per_beat
        merged: dict[int, int] = {0: DEFAULT_TEMPO}
        for tick, tempo in sorted(changes):
            merged[tick] = tempo
        self._ticks = sorted(merged)
        self._tempos = [merged[t] for t in self._ticks]
        self._seconds = [0.0]
        for i in range(1, len(self._ticks)):
            span = self._ticks[i] - self._ticks[i - 1]
            self._seconds.append(self._seconds[-1] + span * self._tempos[i - 1] / 1e6 / ticks_per_beat)

    def seconds(self, tick: int) -> float:
        i = bisect.bisect_right(self._ticks, tick) - 1
        return self._seconds[i] + (tick - self._ticks[i]) * self._tempos[i] / 1e6 / self.ticks_per_beat

    def beats(self, until_seconds: float) -> list[float]:
        out, tick = [], 0
        while (t := self.seconds(tick)) <= until_seconds:
            out.append(t)
            tick += self.ticks_per_beat
        return out

    @property
    def initial_bpm(self) -> float:
        return 60e6 / self._tempos[0]


@dataclass
class _Part:
    name: str = ""
    program: int | None = None
    notes: list[Note] = field(default_factory=list)


def read_midi(path: str | Path) -> Song:
    path = Path(path)
    mid = mido.MidiFile(path, clip=True)
    changes = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "set_tempo":
                changes.append((tick, msg.tempo))
    tempo = TempoMap(mid.ticks_per_beat, changes)

    parts: dict[tuple[int, int], _Part] = defaultdict(_Part)
    pedals: list[tuple[float, float]] = []
    for track_index, track in enumerate(mid.tracks):
        tick, name = 0, ""
        programs: dict[int, int] = {}
        sounding: dict[tuple[int, int], deque] = defaultdict(deque)
        pedal_down: dict[int, int] = {}
        for msg in track:
            tick += msg.time
            if msg.type == "track_name":
                name = msg.name
            elif msg.type == "program_change":
                programs.setdefault(msg.channel, msg.program)
            elif msg.type == "note_on" and msg.velocity > 0:
                if msg.channel != DRUM_CHANNEL:
                    sounding[(msg.channel, msg.note)].append((tick, msg.velocity))
            elif msg.type in ("note_on", "note_off"):
                queue = sounding.get((msg.channel, msg.note))
                if queue:
                    start, velocity = queue.popleft()
                    _add(parts[(track_index, msg.channel)], tempo, msg.note, start, tick, velocity)
            elif msg.type == "control_change" and msg.control == 64:
                if msg.value >= 64:
                    pedal_down.setdefault(msg.channel, tick)
                elif msg.channel in pedal_down:
                    pedals.append((tempo.seconds(pedal_down.pop(msg.channel)), tempo.seconds(tick)))
        for (channel, pitch), queue in sounding.items():  # notes never switched off
            for start, velocity in queue:
                _add(parts[(track_index, channel)], tempo, pitch, start, tick, velocity)
        for (track_i, channel), part in parts.items():
            if track_i == track_index:
                part.name = name
                part.program = programs.get(channel)

    notes_by_part = [p for p in parts.values() if p.notes]
    _tag_roles(notes_by_part)
    notes = sorted((n for p in notes_by_part for n in p.notes), key=lambda n: (n.start, n.pitch))
    if not notes:
        raise ValueError("This MIDI file has no notes (apart from drums).")
    duration = max(n.end for n in notes)
    return Song(
        notes=notes,
        duration=duration,
        source_kind="midi",
        beats=tempo.beats(duration),
        tempo=round(tempo.initial_bpm, 2),
        pedals=_merge_intervals(pedals),
        title=path.stem,
        source_name=path.name,
    )


def _add(part: _Part, tempo: TempoMap, pitch: int, start: int, end: int, velocity: int) -> None:
    t0, t1 = tempo.seconds(start), tempo.seconds(end)
    if t1 > t0:
        part.notes.append(Note(pitch, t0, t1 - t0, velocity))


def _tag_roles(parts: list[_Part]) -> None:
    """Uses track names and instruments to find the melody and bass parts."""
    for part in parts:
        name = part.name.lower()
        role = Role.HARMONY
        if any(word in name for word in BASS_WORDS) or (part.program is not None and 32 <= part.program <= 39):
            role = Role.BASS
        elif any(word in name for word in MELODY_WORDS):
            role = Role.MELODY
        for n in part.notes:
            n.role = role
    if len(parts) < 2 or any(p.notes[0].role is Role.MELODY for p in parts):
        return
    end = max(n.end for p in parts for n in p.notes)
    scored = [(_melody_score(p, end), p) for p in parts if p.notes[0].role is Role.HARMONY]
    if scored:
        score, best = max(scored, key=lambda sp: sp[0])
        if score >= 0.35:
            for n in best.notes:
                n.role = Role.MELODY


def _melody_score(part: _Part, song_end: float) -> float:
    """High for a single-note line in the singing range that plays through most of the song."""
    notes = sorted(part.notes, key=lambda n: n.start)
    if len(notes) < 16:
        return 0.0
    overlaps = sum(1 for a, b in zip(notes, notes[1:]) if b.start < a.end - 0.03)
    single_line = 1 - overlaps / len(notes)
    coverage = min(1.0, 2 * sum(min(n.duration, 2.0) for n in notes) / song_end)
    in_range = 1.0 if 55 <= statistics.mean(n.pitch for n in notes) <= 84 else 0.4
    return single_line * coverage * in_range


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out
