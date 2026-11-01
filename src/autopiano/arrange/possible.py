"""Keyboard-possible mode: every chord sticks to one modifier, the way a real keyboard has to be played.

Holding Shift turns every key into its capital and Ctrl changes them all too, so nobody can press a
lowercase key and a capital, or a Ctrl key and a normal one, at the same moment. The player can fake
it by tapping Shift between the keys of one chord, but with this mode each chord uses one modifier:
the melody's, or else whichever keeps the most of the chord (the bass counts double). Every other note
in the chord is replaced by, in order of preference:

1. the same note an octave or two away, when that one uses the chord's modifier (in 88-key mode the
   Ctrl keys are an octave from normal ones);
2. a nearby copy of a note already sounding, so the harmony stays the same with one note doubled.
   It stays under the melody, and only a replaced bass note goes below the rest of the chord;
3. nothing, when neither fits.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..layout import Layout
from ..models import Note, Role
from .chords import enforce_key_gaps

_WEIGHT = {Role.MELODY: 100.0, Role.BASS: 2.0, Role.HARMONY: 1.0}
OCTAVE_REACH = 36  # semitones a note may move to keep its own pitch
COPY_REACH = 12  # and how far the copy of another chord note may be from the note it replaces


@dataclass
class PossibleReport:
    chords: int = 0  # chords that mixed modifiers
    moved: int = 0  # notes played an octave or two away
    doubled: int = 0  # notes replaced by a copy of another note of the chord
    dropped: int = 0  # notes left out

    @property
    def changed(self) -> int:
        return self.moved + self.doubled + self.dropped


def make_possible(notes: list[Note], layout: Layout) -> tuple[list[Note], PossibleReport]:
    """The notes with no chord mixing modifiers. ``notes`` is left as it was."""
    report = PossibleReport()
    chords: dict[int, list[Note]] = defaultdict(list)
    for n in notes:
        chords[n.chord].append(n)
    out: list[Note] = []
    sounding: list[Note] = []  # notes of earlier chords still held
    for chord in sorted(chords.values(), key=lambda c: min(n.start for n in c)):
        t = min(n.start for n in chord)
        sounding = [n for n in sounding if n.end > t]
        if len({n.modifier for n in chord}) == 1:
            kept = [n.copy() for n in chord]
        else:
            report.chords += 1
            kept = _one_modifier(chord, sounding, layout, report)
        out += kept
        sounding += kept
    spaced = enforce_key_gaps(out)  # a moved note may now share a key with a note held from before
    report.dropped += len(out) - len(spaced)
    return spaced, report


def _one_modifier(chord: list[Note], sounding: list[Note], layout: Layout, report: PossibleReport) -> list[Note]:
    totals: dict = defaultdict(float)
    for n in chord:
        totals[n.modifier] += _WEIGHT[n.role]
    with_bass = {n.modifier for n in chord if n.role is Role.BASS}
    target = max(totals, key=lambda m: (totals[m], m in with_bass, -m))  # on a tie: the bass's, then plain keys

    kept = [n.copy() for n in chord if n.modifier is target]
    # the chord's own tune, or else the one still held from before
    melody = [n.pitch for n in kept if n.role is Role.MELODY] or [n.pitch for n in sounding if n.role is Role.MELODY]
    ceiling = max(melody) if melody else None
    bottom = min(n.pitch for n in chord)
    held_keys = {n.key for n in sounding}
    for n in sorted((n for n in chord if n.modifier is not target), key=lambda n: (-_WEIGHT[n.role], n.pitch)):
        lowest = min(k.pitch for k in kept)
        in_bass = n.pitch == bottom  # it was the chord's lowest note, so its stand-in may go below the rest
        pool = {k.pitch % 12 for k in kept + sounding}
        used_pitches = {k.pitch for k in kept}
        used_keys = {k.key for k in kept}
        best, best_score = None, None
        for pitch, (key, modifier) in layout.keys.items():
            if modifier is not target or pitch in used_pitches or key in used_keys:
                continue
            if ceiling is not None and n.pitch < ceiling <= pitch:
                continue  # the tune stays on top
            if not in_bass and pitch < lowest:
                continue  # and the bass at the bottom
            distance = abs(pitch - n.pitch)
            if pitch % 12 == n.pitch % 12 and distance <= OCTAVE_REACH:
                tier = 0
            elif pitch % 12 in pool and distance <= COPY_REACH:
                tier = 1
            else:
                continue
            # a key that's still held would have to be let go early
            score = (tier, in_bass and pitch > lowest, key in held_keys, distance, pitch)
            if best_score is None or score < best_score:
                best, best_score = (pitch, key, modifier), score
        if best is None:
            report.dropped += 1
            continue
        pitch, key, modifier = best
        role = n.role
        if role is Role.BASS and pitch > lowest:
            role = Role.HARMONY
        kept.append(n.copy(pitch=pitch, key=key, modifier=modifier, role=role))
        if best_score[0] == 0:
            report.moved += 1
        else:
            report.doubled += 1
    return kept
