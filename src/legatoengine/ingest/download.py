"""Downloads a song from a link with yt-dlp: YouTube, SoundCloud, Bandcamp and the
many other sites it knows, or a direct link to an audio or MIDI file.

YouTube only hands its audio to players that run its JavaScript, so YouTube links
need Deno (or Node). Like ffmpeg, they're looked up in Homebrew's folders too,
because apps started from Finder don't get those on PATH.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import CACHE_DIR, DOWNLOADS_DIR
from ..progress import ProgressFn, ignore
from .audio import find_program, install_hint

AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio/best[height<=?720]/best"
JS_RUNTIMES = ("deno", "node", "bun")
_LINK = re.compile(r"https?://[^\s/?#]+\S*", re.IGNORECASE)
_BARE_LINK = re.compile(r"(?:[\w-]+\.)+[a-z]{2,}/\S*", re.IGNORECASE)  # youtu.be/… copied without https://
_STRICT_LINK = re.compile(r"https?://[\w-]+(?:\.[\w-]+)+(?::\d+)?(?:[/?#]\S*)?", re.IGNORECASE)  # a real host name
_WORD_BREAKS = re.compile(r"[\s|<>\"'`()\[\]{}]+")
_OFFLINE = ("nodename nor servname", "Errno 8", "Errno 51", "Errno 61", "timed out", "Connection refused", "getaddrinfo")


class LinkError(Exception):
    """The link couldn't be downloaded. The message is safe to show the user."""


@dataclass
class Download:
    path: Path  # the downloaded song
    title: str
    url: str  # the page it came from


def is_link(text: str) -> bool:
    return _LINK.fullmatch(text.strip()) is not None


def with_scheme(text: str) -> str:
    """Adds https:// to a pasted link that has no scheme, such as youtu.be/dQw4w9WgXcQ."""
    text = text.strip()
    return f"https://{text}" if _BARE_LINK.fullmatch(text) else text


def find_links(text: str) -> list[str]:
    """Every link in pasted text (one per line, a Markdown table or list, …), in order and without repeats."""
    found = []
    for word in _WORD_BREAKS.split(text):
        word = with_scheme(word.rstrip(".,;:!?*"))
        if _STRICT_LINK.fullmatch(word) and word not in found:
            found.append(word)
    return found


def js_runtimes() -> dict[str, dict]:
    """The JavaScript runtimes yt-dlp may use for YouTube, Deno first."""
    return {name: {"path": path} for name in JS_RUNTIMES if (path := find_program(name))}


def download(url: str, folder: Path | None = None, progress: ProgressFn | None = None) -> Download:
    """Saves the song's audio into ``folder`` (default: the Downloads folder in the library),
    replacing an earlier download of the same name."""
    import yt_dlp

    folder = folder or DOWNLOADS_DIR
    report = progress or ignore
    report("Opening the link", 0.0)

    def on_progress(d: dict) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            report("Downloading the song", min(1.0, d.get("downloaded_bytes", 0) / total))
        elif d.get("fragment_count"):
            report("Downloading the song", min(1.0, (d.get("fragment_index") or 0) / d["fragment_count"]))

    log = _Log()
    runtimes = js_runtimes()
    options = {
        "format": AUDIO_FORMAT,
        "paths": {"home": str(folder), "temp": str(CACHE_DIR / "downloads")},  # unfinished files stay out of sight
        "outtmpl": "%(title).180B.%(ext)s",
        "noplaylist": True,  # a video opened from a playlist is just that video
        "playlist_items": "1",
        "overwrites": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": log,
        "progress_hooks": [on_progress],
        "js_runtimes": runtimes or {"deno": {}},
        "cachedir": str(CACHE_DIR / "yt-dlp"),
        "socket_timeout": 30,
    }
    if ffmpeg := find_program("ffmpeg"):
        options["ffmpeg_location"] = ffmpeg
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
            if info.get("_type") in ("playlist", "multi_video"):
                raise LinkError("This link is a playlist or a channel. Open the song you want and use its own link.")
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                raise LinkError("This link is a live stream. Only finished videos and songs can be downloaded.")
            info = ydl.process_ie_result(info, download=True)
            if info.get("_type") in ("playlist", "multi_video"):  # a page that turned out to hold several
                info = next((entry for entry in info.get("entries") or [] if entry), {})
    except yt_dlp.utils.DownloadError as e:
        raise LinkError(_explain(str(e), log.warnings, bool(runtimes))) from e
    files = [Path(d["filepath"]) for d in info.get("requested_downloads") or [] if d.get("filepath")]
    if not files or not files[-1].is_file():
        raise LinkError("Nothing could be downloaded from this link.")
    return Download(files[-1], info.get("title") or files[-1].stem, info.get("webpage_url") or url)


class _Log:
    """Keeps yt-dlp quiet. Its warnings help explain a failure."""

    def __init__(self):
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        pass


def _explain(message: str, warnings: list[str], have_js: bool) -> str:
    """yt-dlp's error, shortened and without its command-line advice."""
    text = re.sub(r"^ERROR:\s*", "", message.strip())
    text = re.sub(r"^\[[\w:]+\]\s*(?:[\w-]+:\s+)?", "", text)  # "[youtube] dQw4w9WgXcQ: "
    text = re.split(r"\s+(?:Use --|See  ?https?://|\(caused by)", text)[0].strip()
    if "Unsupported URL" in text:
        return (
            "LegatoEngine can't find a song at this link. Links to YouTube, SoundCloud, Bandcamp and most other "
            "video and music sites work, and so do direct links to audio files."
        )
    if any(s in message for s in _OFFLINE):
        return "Couldn't reach the site. Check your internet connection and try again."
    if not have_js and any("JavaScript runtime" in w for w in warnings):
        return f"Couldn't download this link: {text}\n\nYouTube links need Deno. Install it with: {install_hint('deno')}"
    return f"Couldn't download this link: {text}"
