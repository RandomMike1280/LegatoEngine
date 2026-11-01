"""Keyboard layouts: which computer key, plus which modifier, plays each piano pitch.

Layouts live in ``layouts/*.json`` so a mapping can be corrected for a particular
game without touching code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from .models import Modifier

LAYOUT_DIR = Path(__file__).parent / "layouts"
WHITE_PITCH_CLASSES = frozenset({0, 2, 4, 5, 7, 9, 11})
_MODIFIERS = {"none": Modifier.NONE, "shift": Modifier.SHIFT, "ctrl": Modifier.CTRL}


def is_black(pitch: int) -> bool:
    return pitch % 12 not in WHITE_PITCH_CLASSES


@dataclass(frozen=True)
class Layout:
    id: str
    name: str
    description: str
    low: int
    high: int
    keys: dict[int, tuple[str, Modifier]]  # pitch -> (physical key, modifier)

    def lookup(self, pitch: int) -> tuple[str, Modifier] | None:
        return self.keys.get(pitch)

    def contains(self, pitch: int) -> bool:
        return pitch in self.keys

    @property
    def physical_keys(self) -> frozenset[str]:
        return frozenset(k for k, _ in self.keys.values())


def build_layout(data: dict) -> Layout:
    low = data["low"]
    if low % 12 not in WHITE_PITCH_CLASSES:
        raise ValueError("a layout must start on a white key")
    keys: dict[int, tuple[str, Modifier]] = {}
    white = data["white_keys"]
    pitch, i, last_white = low, 0, ""
    while i < len(white):
        if pitch % 12 in WHITE_PITCH_CLASSES:
            last_white = white[i]
            keys[pitch] = (last_white, Modifier.NONE)
            i += 1
        else:
            keys[pitch] = (last_white, Modifier.SHIFT)
        pitch += 1
    for run in data.get("extra", []):
        modifier = _MODIFIERS[run["modifier"]]
        for offset, key in enumerate(run["keys"]):
            keys[run["first_pitch"] + offset] = (key, modifier)

    combos = list(keys.values())
    if len(set(combos)) != len(combos):
        raise ValueError(f"layout {data['id']} maps two pitches to the same key")
    return Layout(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        low=min(keys),
        high=max(keys),
        keys=dict(sorted(keys.items())),
    )


@cache
def load_layout(layout_id: str) -> Layout:
    path = LAYOUT_DIR / f"{layout_id}.json"
    if not path.exists():
        raise KeyError(f"unknown layout {layout_id!r}")
    return build_layout(json.loads(path.read_text()))


def list_layouts() -> list[Layout]:
    return [load_layout(p.stem) for p in sorted(LAYOUT_DIR.glob("*.json"))]
