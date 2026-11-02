"""Where LegatoEngine keeps its files: on macOS in the usual Library folders, on Windows in the
local app data folder. Scripts go in Music on both."""

import os
import re
import sys
from pathlib import Path


NAME = "LegatoEngine"
OLD_NAME = "AutoPiano"  # what LegatoEngine was called at first


def _app_folders(platform: str, home: Path, environ, name: str = NAME) -> tuple[Path, Path]:
    """The transcription cache's folder and the downloaded model weights' folder."""
    if platform == "win32":
        local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / name
        return local / "Cache", local / "models"
    return home / "Library" / "Caches" / name, home / "Library" / "Application Support" / name / "models"


def _renamed_folders(platform: str, home: Path, environ) -> list[tuple[Path, Path]]:
    """Each folder that had AutoPiano's name, and the folder it moves to."""
    old, new = _app_folders(platform, home, environ, OLD_NAME), _app_folders(platform, home, environ)
    pairs = [(home / "Music" / OLD_NAME, home / "Music" / NAME), (old[1].parent, new[1].parent)]
    if old[0].parent != old[1].parent:  # on macOS the cache has a folder of its own
        pairs.append((old[0], new[0]))
    return pairs


def move_old_folders(platform: str = sys.platform, home: Path | None = None, environ=os.environ) -> list[Path]:
    """Gives the scripts, the cache and the downloaded models from before the rename their new
    folders, unless a new folder already has something in it. Returns the folders moved to."""
    moved = []
    for old, new in _renamed_folders(platform, home or Path.home(), environ):
        if old.is_dir() and not _in_use(new):
            try:
                if new.exists():
                    new.rmdir()  # empty: made by something that ran before the move
                old.rename(new)
            except OSError:
                continue
            moved.append(new)
    return moved


def _in_use(folder: Path) -> bool:
    try:
        return any(folder.iterdir())
    except FileNotFoundError:
        return False
    except OSError:
        return True


CACHE_DIR, MODELS_DIR = _app_folders(sys.platform, Path.home(), os.environ)
LIBRARY_DIR = Path.home() / "Music" / NAME  # saved .apno scripts
DOWNLOADS_DIR = LIBRARY_DIR / "Downloads"  # songs downloaded from links

_FORBIDDEN = r"[/:\\\x00-\x1f]"
_FORBIDDEN_ON_WINDOWS = r'[/:\\<>"|?*\x00-\x1f]'
_RESERVED_ON_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"{port}{i}" for port in ("COM", "LPT") for i in range(1, 10))}


def safe_filename(title: str, windows: bool = sys.platform == "win32") -> str:
    """A file name (without extension) made from a song title. Windows forbids more characters,
    names such as CON or NUL, and names that end in a space or a dot."""
    name = re.sub(_FORBIDDEN_ON_WINDOWS if windows else _FORBIDDEN, "-", title).strip(" .") or "Untitled"
    name = name[:100]
    if windows:
        name = name.rstrip(" .")
        if name.split(".")[0].strip().upper() in _RESERVED_ON_WINDOWS:
            name = "_" + name
    return name
