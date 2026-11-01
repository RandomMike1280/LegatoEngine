"""Thins chords down to what sounds clear on a Roblox piano.

Priority inside a chord: the melody note, then the bass note, then harmony notes,
preferring ones that add a new pitch class over octave doublings, then louder and
longer ones. Optionally harmony is kept under the melody so the tune stays on top.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from ..layout import Layout
from ..models import Note, Role


@dataclass(frozen=True)
class ThinRules:
    max_keys: int = 8
    roles: frozenset[Role] = frozenset(Role)
    harmony_min_duration: float = 0.0  # drop shorter harmony notes
    harmony_min_spacing: float = 0.0  # drop harmony-only chords closer than this to the last one
    melody_on_top: bool = False  # move harmony above the melody down an octave (or drop it)


class _MelodyLine:
    def __init__(self, notes: list[Note]):
        self.notes = sorted((n for n in notes if n.role is Role.MELODY), key=lambda n: n.start)
        self.starts = [n.start for n in self.notes]

    def highest_at(self, t: float) -> int | None:
        """Pitch of the highest melody note sounding at ``t``."""
        i = bisect.bisect_right(self.starts, t + 1e-9)
        best = None
        for n in self.notes[max(0, i - 4) : i]:
            if n.start <= t + 1e-9 < n.end and (best is None or n.pitch > best):
                best = n.pitch
        return best


def thin_chords(chords: list[list[Note]], layout: Layout, rules: ThinRules) -> list[list[Note]]:
    melody_line = _MelodyLine([n for chord in chords for n in chord])
    out: list[list[Note]] = []
    last_harmony = float("-inf")
    for chord in chords:
        t = chord[0].start
        melody = sorted((n for n in chord if n.role is Role.MELODY), key=lambda n: -n.pitch)
        bass = sorted((n for n in chord if n.role is Role.BASS), key=lambda n: n.pitch)
        harmony = [n for n in chord if n.role is Role.HARMONY]
        for extra in melody[1:] + bass[1:]:  # double stops and octave basses: keep the outer note
            extra.role = Role.HARMONY
            harmony.append(extra)
        melody, bass = melody[:1], bass[:1]
        if Role.MELODY not in rules.roles:
            melody = []
        if Role.BASS not in rules.roles:
            bass = []
        if Role.HARMONY not in rules.roles:
            harmony = []

        if rules.melody_on_top and harmony:
            top = melody_line.highest_at(t)
            if top is not None:
                harmony = [m for n in harmony if (m := _below(n, top, layout)) is not None]
        harmony = [n for n in harmony if n.duration >= rules.harmony_min_duration]
        if harmony and not melody and not bass and t - last_harmony < rules.harmony_min_spacing:
            harmony = []

        chosen: list[Note] = []
        for n in melody + bass:
            if len(chosen) < rules.max_keys and all(n.key != c.key for c in chosen):
                chosen.append(n)
        while harmony and len(chosen) < rules.max_keys:
            used_keys = {c.key for c in chosen}
            used_pitches = {c.pitch for c in chosen}
            used_classes = {c.pitch % 12 for c in chosen}
            harmony = [n for n in harmony if n.key not in used_keys and n.pitch not in used_pitches]
            if not harmony:
                break
            best = min(harmony, key=lambda n: (n.pitch % 12 in used_classes, -n.velocity, -n.duration))
            chosen.append(best)
            harmony.remove(best)
            last_harmony = t
        if chosen:
            out.append(chosen)
    return out


def _below(n: Note, ceiling: int, layout: Layout) -> Note | None:
    pitch = n.pitch
    while pitch >= ceiling:
        pitch -= 12
    if pitch == n.pitch:
        return n
    mapping = layout.lookup(pitch)
    if mapping is None:
        return None
    return n.copy(pitch=pitch, key=mapping[0], modifier=mapping[1])
