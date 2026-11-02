"""Core data types shared by ingest, arrangement, the script format and the player."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import IntEnum


class Role(IntEnum):
    """The part a note plays. A higher value wins when notes compete for a slot."""

    HARMONY = 0
    BASS = 1
    MELODY = 2


class Modifier(IntEnum):
    NONE = 0
    SHIFT = 1
    CTRL = 2


@dataclass(slots=True)
class Note:
    pitch: int  # MIDI note number, 60 = middle C
    start: float  # seconds
    duration: float  # seconds the key is held
    velocity: int = 80  # 1..127
    role: Role = Role.HARMONY
    # Filled in by the arranger.
    chord: int = -1
    key: str = ""  # physical key, e.g. "t"
    modifier: Modifier = Modifier.NONE

    @property
    def end(self) -> float:
        return self.start + self.duration

    def copy(self, **changes) -> Note:
        return replace(self, **changes)


@dataclass
class Song:
    """Raw notes pulled out of a source file, before arrangement."""

    notes: list[Note]
    duration: float
    source_kind: str  # "midi" | "piano" | "full"
    beats: list[float] = field(default_factory=list)
    tempo: float = 120.0
    pedals: list[tuple[float, float]] = field(default_factory=list)
    title: str = ""
    source_name: str = ""
    source_hash: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["notes"] = [[n.pitch, n.start, n.duration, n.velocity, int(n.role)] for n in self.notes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Song:
        d = dict(d)
        d["notes"] = [Note(p, s, du, v, Role(r)) for p, s, du, v, r in d["notes"]]
        d["pedals"] = [tuple(p) for p in d.get("pedals", [])]
        return cls(**d)


@dataclass
class ScriptMeta:
    title: str
    source_name: str = ""
    source_hash: str = ""
    source_kind: str = ""
    duration: float = 0.0
    bpm: float = 0.0
    key_name: str = ""  # detected key of the source
    transpose: int = 0  # semitones applied
    layout_id: str = "vp61"
    preset: str = "full"
    settings: dict = field(default_factory=dict)
    converter_version: str = ""
    created: float = 0.0


@dataclass
class Script:
    """An arranged song ready for the player. This is what a .apno file holds."""

    meta: ScriptMeta
    notes: list[Note]  # sorted by start; every note has key, modifier and chord set
    beats: list[float] = field(default_factory=list)
    pedals: list[tuple[float, float]] = field(default_factory=list)

    @property
    def chord_count(self) -> int:
        return len({n.chord for n in self.notes})

    @property
    def end_time(self) -> float:
        return max((n.end for n in self.notes), default=0.0)
