"""Turns raw notes into a playable script: the arrangement algorithms in order."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from .. import __version__
from ..layout import load_layout
from ..models import Note, Role, Script, ScriptMeta, Song
from .chords import enforce_key_gaps, group_chords
from .cleanup import clean
from .key import choose_transpose, detect_key, key_name
from .range_fit import fit_to_range
from .reduce import ThinRules, thin_chords
from .roles import assign_skyline_roles
from .tempo import quantize_chords


class ArrangeError(Exception):
    """Nothing playable was left. The message is safe to show the user."""


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    max_keys: int
    roles: frozenset[Role]
    harmony_min_duration: float = 0.0
    harmony_min_spacing: float = 0.0


PRESETS = {
    p.id: p
    for p in (
        Preset("full", "Full", "Every part, up to 8 keys at once", 8, frozenset(Role)),
        Preset("simplified", "Simplified", "Melody, bass and lighter chords", 4, frozenset(Role), 0.12, 0.18),
        Preset("melody_bass", "Melody + bass", "Just the tune and the bass line", 2, frozenset({Role.MELODY, Role.BASS})),
        Preset("melody", "Melody only", "Just the tune, one key at a time", 1, frozenset({Role.MELODY})),
    )
}


@dataclass
class ArrangeSettings:
    preset: str = "full"
    layout_id: str = "vp61"
    transpose: int | str = "auto"  # "auto" (fewest black keys), "original", or semitones
    max_keys: int = 0  # 0 uses the preset's limit
    quantize: float = 0.0  # 0..1, how strongly chords snap to the beat grid
    subdivision: int = 4  # grid steps per beat
    chord_window: float = 0.025  # notes starting this close together are one chord

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ArrangeSettings:
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


# Cleanup is tuned to the source: MIDI is exact, transcriptions have noise. In full songs, the
# separator cuts notes' decays short, so even 30-60 ms notes are mostly real, and quiet octaves
# above loud notes are real about as often as overtones: keeping both scored better on 40 test
# songs (all notes of the arranged script, F1 0.515 against 0.485).
_CLEANUP = {
    "midi": dict(min_duration=0.0, min_velocity=1, remove_overtones=False),
    "piano": dict(min_duration=0.04, min_velocity=12, remove_overtones=True),
    "full": dict(min_duration=0.03, min_velocity=15, remove_overtones=False),
}


def arrange(song: Song, settings: ArrangeSettings | None = None) -> Script:
    s = settings or ArrangeSettings()
    preset = PRESETS[s.preset]
    layout = load_layout(s.layout_id)
    # A note still ringing when a recording ends gets the piano model's longest length, past the end.
    end = song.duration or float("inf")
    notes = [n.copy(duration=min(n.duration, end - n.start)) for n in song.notes if n.start < end]

    assign_skyline_roles(notes)
    notes = clean(notes, **_CLEANUP.get(song.source_kind, _CLEANUP["midi"]))
    if not notes:
        raise ArrangeError("No notes were found in this song.")

    tonic, mode = detect_key(notes)
    if s.transpose == "auto":
        shift = choose_transpose(notes, layout)
    elif s.transpose == "original":
        shift = 0
    else:
        shift = int(s.transpose)
    for n in notes:
        n.pitch += shift

    notes = fit_to_range(notes, layout.low, layout.high, move_lines=song.source_kind == "full")
    for n in notes:
        n.key, n.modifier = layout.lookup(n.pitch)

    chords = group_chords(notes, s.chord_window)
    if s.quantize > 0:
        quantize_chords(chords, song.beats, s.quantize, s.subdivision)
        chords = group_chords([n for chord in chords for n in chord], s.chord_window)

    rules = ThinRules(
        max_keys=s.max_keys or preset.max_keys,
        roles=preset.roles,
        harmony_min_duration=preset.harmony_min_duration,
        harmony_min_spacing=preset.harmony_min_spacing,
        melody_on_top=song.source_kind == "full" or s.preset != "full",
    )
    chords = thin_chords(chords, layout, rules)
    notes = enforce_key_gaps([n for chord in chords for n in chord])
    if not notes:
        raise ArrangeError("Nothing was left to play with these settings.")
    for n in notes:  # scripts store milliseconds; round now so a saved script plays identically
        n.start = round(n.start, 3)
        n.duration = max(0.001, round(n.duration, 3))
    number_chords(notes)

    meta = ScriptMeta(
        title=song.title,
        source_name=song.source_name,
        source_hash=song.source_hash,
        source_kind=song.source_kind,
        duration=max(n.end for n in notes),
        bpm=song.tempo,
        key_name=key_name(tonic, mode),
        transpose=shift,
        layout_id=layout.id,
        preset=preset.id,
        settings=s.to_dict(),
        converter_version=__version__,
        created=time.time(),
    )
    return Script(meta=meta, notes=notes, beats=list(song.beats), pedals=list(song.pedals))


def number_chords(notes: list[Note]) -> None:
    """Gives notes that start together the same chord number (notes sorted by start)."""
    chord, last = -1, None
    for n in notes:  # sorted by start
        if n.start != last:
            chord += 1
            last = n.start
        n.chord = chord
