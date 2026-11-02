"""Where AutoPiano keeps its files: on macOS in the usual Library folders, on Windows in the
local app data folder. Scripts go in Music on both."""

import os
import re
import sys
from pathlib import Path


def _app_folders(platform: str, home: Path, environ) -> tuple[Path, Path]:
    """The transcription cache's folder and the downloaded model weights' folder."""
    if platform == "win32":
        local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local") / "AutoPiano"
        return local / "Cache", local / "models"
    return home / "Library" / "Caches" / "AutoPiano", home / "Library" / "Application Support" / "AutoPiano" / "models"


CACHE_DIR, MODELS_DIR = _app_folders(sys.platform, Path.home(), os.environ)
LIBRARY_DIR = Path.home() / "Music" / "AutoPiano"  # saved .apno scripts
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
