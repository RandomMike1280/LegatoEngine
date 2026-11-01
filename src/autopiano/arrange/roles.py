"""Finds the melody and bass in songs that don't come with separate parts."""

from __future__ import annotations

from ..models import Note, Role


def onset_groups(notes: list[Note], window: float) -> list[list[Note]]:
    """Notes sorted into groups that start within ``window`` of the group's first note."""
    groups: list[list[Note]] = []
    for n in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if groups and n.start - groups[-1][0].start <= window:
            groups[-1].append(n)
        else:
            groups.append([n])
    return groups


def assign_skyline_roles(
    notes: list[Note], window: float = 0.03, melody_floor: int = 48, bass_ceiling: int = 55
) -> None:
    """The top voice is the melody and the lowest voice the bass ("skyline").

    A note struck under a melody note that is still ringing is accompaniment, not a
    new melody note. Parts that already have a role are left alone.
    """
    need_melody = not any(n.role is Role.MELODY for n in notes)
    need_bass = not any(n.role is Role.BASS for n in notes)
    if not (need_melody or need_bass):
        return
    last_melody: Note | None = None
    for group in onset_groups(notes, window):
        top = max(group, key=lambda n: n.pitch)
        if (
            need_melody
            and top.role is Role.HARMONY
            and top.pitch >= melody_floor
            and not (last_melody and last_melody.end > top.start + 0.05 and top.pitch < last_melody.pitch)
        ):
            top.role = Role.MELODY
            last_melody = top
        if need_bass and len(group) > 1:
            low = min(group, key=lambda n: n.pitch)
            if low.role is Role.HARMONY and low.pitch <= bass_ceiling:
                low.role = Role.BASS
