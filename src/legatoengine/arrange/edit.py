"""Simple changes to a finished script: trim it, move it up or down, change its tempo,
leave out parts, press fewer keys at once, or move it to the other piano.

Edits always start from the script as it was opened, so they can be changed or undone
in any order. A changed script goes through the arranger's last steps again: notes
pushed out of the piano's range fold back by octaves, each chord keeps one note per
physical key, and there's still a gap before any key is pressed again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from .. import __version__
from ..layout import load_layout
from ..models import Role, Script
from .chords import enforce_key_gaps, group_chords
from .pipeline import number_chords
from .range_fit import fit_to_range
from .reduce import ThinRules, thin_chords

PART_NAMES = {Role.MELODY: "melody", Role.BASS: "bass", Role.HARMONY: "chords"}
MIN_TEMPO, MAX_TEMPO = 0.25, 4.0
_ANY_NUMBER_OF_KEYS = 99


class EditError(Exception):
    """The edit can't be made. The message is safe to show the user."""


@dataclass
class Edits:
    start: float = 0.0  # seconds into the original script where the edited one begins
    end: float | None = None  # where it stops; None is the end
    transpose: int = 0  # semitones
    tempo: float = 1.0  # 1.25 plays 25% faster
    parts: frozenset[Role] = field(default_factory=lambda: frozenset(Role))
    max_keys: int = 0  # most keys at once; 0 keeps what the script has
    layout_id: str | None = None  # another piano; None keeps the script's
    title: str | None = None

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "transpose": self.transpose,
            "tempo": self.tempo,
            "parts": sorted(int(r) for r in self.parts),
            "max_keys": self.max_keys,
            "layout_id": self.layout_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Edits:
        d = dict(d)
        d["parts"] = frozenset(Role(r) for r in d.get("parts", list(Role)))
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})

    def describe(self) -> str:
        """In words, such as "trimmed to 0:12–2:30, up 2 semitones, 110% tempo"."""
        out = []
        if self.start > 0 or self.end is not None:
            end = clock(self.end) if self.end is not None else "the end"
            out.append(f"trimmed to {clock(self.start)}–{end}")
        if self.transpose:
            steps = abs(self.transpose)
            out.append(f"{'up' if self.transpose > 0 else 'down'} {steps} semitone{'s' if steps != 1 else ''}")
        if round(self.tempo * 100) != 100:
            out.append(f"{round(self.tempo * 100)}% tempo")
        if missing := [name for role, name in PART_NAMES.items() if role not in self.parts]:
            out.append("without " + " and ".join(missing))
        if self.max_keys:
            out.append(f"at most {self.max_keys} key{'s' if self.max_keys != 1 else ''} at once")
        if self.layout_id:
            out.append(f"moved to {load_layout(self.layout_id).name}")
        return ", ".join(out)


def clock(seconds: float) -> str:
    """1:05, or 1:05.3 when it isn't a whole second."""
    tenths = round(max(0.0, seconds) * 10)
    minutes, rest = divmod(tenths, 600)
    return f"{minutes}:{rest // 10:02d}" + (f".{rest % 10}" if rest % 10 else "")


def edit_script(script: Script, edits: Edits) -> Script:
    meta = script.meta
    layout = load_layout(edits.layout_id or meta.layout_id)
    start = max(0.0, edits.start)
    end = meta.duration if edits.end is None else min(edits.end, meta.duration)
    if end - start < 0.05:
        raise EditError("The start has to come before the end.")
    if not MIN_TEMPO <= edits.tempo <= MAX_TEMPO:
        raise EditError(f"The tempo has to be between {MIN_TEMPO:.0%} and {MAX_TEMPO:.0%}.")
    tempo = edits.tempo

    def at(t: float) -> float:  # a time in the original script -> the same moment in the edited one
        return (t - start) / tempo

    notes = [
        n.copy(start=at(n.start), duration=(min(n.end, end) - n.start) / tempo)
        for n in script.notes
        if start - 1e-6 <= n.start < end and n.role in edits.parts
    ]
    if edits.transpose or layout.id != meta.layout_id:
        for n in notes:
            n.pitch += edits.transpose
        notes = fit_to_range(notes, layout.low, layout.high)
        for n in notes:
            n.key, n.modifier = layout.lookup(n.pitch)
    chords = group_chords(notes, 0.0005)  # chords already share one start time
    rules = ThinRules(max_keys=edits.max_keys or _ANY_NUMBER_OF_KEYS)
    notes = enforce_key_gaps([n for chord in thin_chords(chords, layout, rules) for n in chord])
    if not notes:
        raise EditError("Nothing is left to play with these changes.")
    for n in notes:
        n.start = round(n.start, 3)
        n.duration = max(0.001, round(n.duration, 3))
    number_chords(notes)

    history = [*meta.settings.get("edits", []), edits.to_dict()]
    new_meta = replace(
        meta,
        title=(edits.title or "").strip() or meta.title,
        duration=max(n.end for n in notes),
        bpm=round(meta.bpm * tempo, 1),
        transpose=meta.transpose + edits.transpose,
        layout_id=layout.id,
        settings={**meta.settings, "edits": history},
        converter_version=__version__,
        created=time.time(),
    )
    beats_end = end if edits.end is not None else float("inf")
    beats = [round(at(b), 3) for b in script.beats if start <= b < beats_end]
    pedals = [(round(at(max(s, start)), 3), round(at(min(e, end)), 3)) for s, e in script.pedals if s < end and e > start]
    return Script(meta=new_meta, notes=notes, beats=beats, pedals=pedals)
