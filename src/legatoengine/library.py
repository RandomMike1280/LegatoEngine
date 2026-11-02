"""The script library: every .apno under ~/Music/AutoPiano, and finding scripts in it.

Searching forgives what people get wrong when they type a song's name: case, accents
("fur elise" finds "Für Elise"), punctuation, spacing ("bwv846" finds "BWV 846") and
small typos ("moonlite" finds "Moonlight"). Every word of the search has to match.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .format.apno import EXTENSION, ApnoError, read_script

SORTS = {"newest": "Newest first", "name": "Name", "length": "Length"}

# Letters that Unicode doesn't split into a base letter and an accent.
_LETTERS = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "đ": "d", "ð": "d", "ł": "l", "þ": "th", "ı": "i",
                          "#": " sharp ", "♯": " sharp ", "♭": " flat "})
_SEPARATORS = re.compile(r"[\W_]+")
_LETTER_DIGIT = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])")

# How much a match counts, by where it was found.
_TITLE, _FILE_NAME, _FOLDER, _DETAILS = 1.0, 0.9, 0.8, 0.6


@dataclass(frozen=True)
class Entry:
    """One script in the library, as the list and the search see it."""

    path: Path
    title: str
    folder: str = ""  # the subfolder it's in, such as "Classical"; "" at the top of the library
    duration: float = 0.0
    key_name: str = ""
    source_kind: str = ""
    layout_id: str = ""
    modified: float = 0.0
    readable: bool = True


def words(text: str) -> list[str]:
    """The words of ``text`` as the search compares them: lower case, without accents or punctuation."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    text = _LETTER_DIGIT.sub(" ", _SEPARATORS.sub(" ", text.translate(_LETTERS)))
    return text.split()


# ---- reading the folder

_seen: dict[Path, dict[Path, tuple[tuple[int, int], Entry]]] = {}  # per library: path -> (mtime and size, entry)


def _walk(root: Path) -> Iterator[tuple[Path, list[str]]]:
    """Each folder under ``root`` with its file names, skipping hidden folders."""
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        yield Path(folder), files


def folders(root: Path | None = None) -> list[Path]:
    """The library folder and every folder inside it."""
    root = root or paths.LIBRARY_DIR
    return [folder for folder, _ in _walk(root)] if root.is_dir() else []


def _read(path: Path, root: Path, modified: float) -> Entry:
    folder = "" if path.parent == root else path.parent.relative_to(root).as_posix()
    try:
        meta = read_script(path).meta
    except ApnoError:
        return Entry(path, path.stem, folder, modified=modified, readable=False)
    return Entry(path, meta.title or path.stem, folder, meta.duration, meta.key_name, meta.source_kind,
                 meta.layout_id, modified)


def scan(root: Path | None = None) -> list[Entry]:
    """Every script in the library folder and its subfolders, newest first.

    Scripts that haven't changed since the last scan aren't read again.
    """
    root = root or paths.LIBRARY_DIR
    if not root.is_dir():
        return []
    known, seen = _seen.get(root, {}), {}
    for folder, files in _walk(root):
        for name in files:
            if name.startswith(".") or not name.endswith(EXTENSION):
                continue
            path = folder / name
            try:
                stat = path.stat()
            except OSError:
                continue
            stamp = (stat.st_mtime_ns, stat.st_size)
            cached = known.get(path)
            seen[path] = cached if cached and cached[0] == stamp else (stamp, _read(path, root, stat.st_mtime))
    _seen[root] = seen
    return sort_entries([entry for _, entry in seen.values()])


def sort_entries(entries: list[Entry], by: str = "newest") -> list[Entry]:
    """``by`` is a key of SORTS. Names sort the way people count: "Idea 9" comes before "Idea 10"."""
    if by == "name":
        return sorted(entries, key=lambda e: _natural(e.title))
    if by == "length":
        return sorted(entries, key=lambda e: (e.duration, _natural(e.title)))
    return sorted(entries, key=lambda e: e.modified, reverse=True)


def _natural(text: str) -> list[tuple[int, int, str]]:
    return [(0, int(w), "") if w.isdigit() else (1, 0, w) for w in words(text)]


# ---- searching


def search(entries: list[Entry], query: str) -> list[Entry]:
    """The entries that match every word of ``query``, best first. Equally good matches keep their order.

    An empty query keeps every entry.
    """
    tokens = words(query)
    if not tokens:
        return list(entries)
    scored = [(_score(entry, tokens), i, entry) for i, entry in enumerate(entries)]
    return [entry for score, _, entry in sorted(scored, key=lambda s: (-s[0], s[1])) if score > 0]


def _score(entry: Entry, tokens: list[str]) -> float:
    total = 0.0
    key = words(entry.key_name)
    at = _find(tokens, key)
    if at >= 0:  # the search names the script's key, such as "a minor"; part of a key isn't enough
        tokens = tokens[:at] + tokens[at + len(key) :]
        total += _DETAILS * len(key)
    title = words(entry.title)
    fields = [
        (_TITLE, title, True),
        (_FILE_NAME, words(entry.path.stem), True),
        (_FOLDER, words(entry.folder), True),
        (_DETAILS, _details(entry), False),  # whole words only
    ]
    compact = ["".join(title), "".join(fields[1][1])]
    for token in tokens:
        best = max((weight * _match(token, word, loose) for weight, found, loose in fields for word in found), default=0)
        if not best and len(token) >= 3 and any(token in text for text in compact):
            best = 0.45  # "bwv846" in "BWV 846", "lalaland" in "La La Land"
        if not best:
            return 0.0
        total += best
    return total + (_phrase_bonus(title, tokens) if tokens else 0.0)


def _find(tokens: list[str], phrase: list[str]) -> int:
    """Where ``phrase`` starts in ``tokens``, or -1."""
    for i in range(len(tokens) - len(phrase) + 1) if phrase else ():
        if tokens[i : i + len(phrase)] == phrase:
            return i
    return -1


def _details(entry: Entry) -> list[str]:
    found = words(entry.source_kind)
    if entry.layout_id:
        found += [w for w in words(entry.layout_id) if w.isdigit()]  # "vp88" -> "88"
    return found


def _match(token: str, word: str, loose: bool) -> float:
    if word == token:
        return 1.0
    if not loose:
        return 0.0
    if word.startswith(token):
        return 0.7 + 0.25 * len(token) / len(word)
    if len(token) >= 3 and token in word:
        return 0.5
    allowed = 0 if token.isdigit() else _typos_allowed(token)  # "2023" is not a typo for "2024"
    if allowed and min(_distance(token, word, allowed), _distance(token, word[: len(token)], allowed)) <= allowed:
        return 0.4
    return 0.0


def _phrase_bonus(title: list[str], tokens: list[str]) -> float:
    """Extra for titles that hold the search as it was typed: more when the title starts with it."""
    *whole, last = tokens
    for i in range(len(title) - len(tokens) + 1):
        if title[i : i + len(whole)] == whole and title[i + len(whole)].startswith(last):
            return 0.8 if i == 0 else 0.5
    return 0.0


def _typos_allowed(token: str) -> int:
    return 0 if len(token) < 4 else 1 if len(token) < 8 else 2


def _distance(a: str, b: str, limit: int) -> int:
    """Edit distance from ``a`` to ``b``, counting a swap of neighbouring letters as one edit.

    Stops early and returns ``limit + 1`` once the distance is past ``limit``.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before, previous = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            row[j] = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (ca != cb))
            if before is not None and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                row[j] = min(row[j], before[j - 2] + 1)
        if min(row) > limit:
            return limit + 1
        before, previous = previous, row
    return previous[-1]
