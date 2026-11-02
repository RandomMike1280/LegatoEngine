"""Remembers transcriptions, so re-arranging a song with new settings is instant."""

from __future__ import annotations

from pathlib import Path

from ..format.apno import ApnoError, seal, unseal
from ..models import Song
from ..paths import CACHE_DIR

CACHE_VERSION = 8  # bump when transcription changes, so old results are redone
MAGIC = b"APNC"


def _path(digest: str, kind: str) -> Path:
    return CACHE_DIR / "songs" / f"{digest}-{kind}-v{CACHE_VERSION}.apnc"


def load(digest: str, kind: str) -> Song | None:
    try:
        return Song.from_dict(unseal(_path(digest, kind).read_bytes(), magic=MAGIC))
    except (OSError, ApnoError, KeyError, TypeError, ValueError):
        return None


def save(song: Song, kind: str) -> None:
    path = _path(song.source_hash, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(seal(song.to_dict(), magic=MAGIC))
    tmp.replace(path)
