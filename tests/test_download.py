"""Downloading from links, against a web server on this Mac (nothing goes to the internet)."""

import functools
import http.server
import socket
import threading

import pytest
import soundfile

from autopiano import cli
from autopiano.format.apno import read_script
from autopiano.ingest import download as dl
from autopiano.ingest.download import LinkError, download, find_links, is_link, with_scheme
from autopiano.models import Note
from autopiano.synth import render

from .helpers import write_midi


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Serves tmp_path/site at a local address; downloads go to tmp_path/downloads."""
    root = tmp_path / "site"
    root.mkdir()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(dl, "DOWNLOADS_DIR", tmp_path / "downloads")
    monkeypatch.setattr(dl, "CACHE_DIR", tmp_path / "cache")
    yield root, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_is_link():
    assert is_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_link("  http://example.com/song.mp3 ")
    assert not is_link("song.mp3")
    assert not is_link("/Users/me/Music/song.mp3")
    assert not is_link("https://")
    assert not is_link("see https://example.com")


def test_find_links_in_pasted_text():
    text = """Songs to try:
| 1 | River Flows in You | https://www.youtube.com/watch?v=7maJOI3QMu0 |
- [Nuvole Bianche](https://www.youtube.com/watch?v=4VR-6AS0-l4).
youtu.be/PaXKf0JEzEA, and again https://www.youtube.com/watch?v=7maJOI3QMu0
grep -oE 'https://www\\.youtube\\.com/watch\\?v=[A-Za-z0-9_-]{11}' "list.md"
not links: song.mp3 ~/Music/AutoPiano/Covers/ https:// http://localhost/x"""
    assert find_links(text) == [
        "https://www.youtube.com/watch?v=7maJOI3QMu0",
        "https://www.youtube.com/watch?v=4VR-6AS0-l4",
        "https://youtu.be/PaXKf0JEzEA",
    ]
    assert find_links("") == []


def test_links_pasted_without_https():
    assert with_scheme("youtu.be/dQw4w9WgXcQ") == "https://youtu.be/dQw4w9WgXcQ"
    assert with_scheme(" www.youtube.com/watch?v=dQw4w9WgXcQ ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert with_scheme("https://soundcloud.com/a/b") == "https://soundcloud.com/a/b"
    assert with_scheme("song.mp3") == "song.mp3"
    assert with_scheme("not a link") == "not a link"


def test_downloads_a_direct_link_to_audio(site, tmp_path):
    root, base = site
    soundfile.write(root / "Moonlight.wav", render([Note(69, 0, 1.0, 100)], 44100), 44100)
    seen = []
    got = download(f"{base}/Moonlight.wav", progress=lambda label, fraction: seen.append((label, fraction)))
    assert got.path == tmp_path / "downloads" / "Moonlight.wav"
    assert got.path.read_bytes() == (root / "Moonlight.wav").read_bytes()
    assert got.title == "Moonlight"
    assert seen[0] == ("Opening the link", 0.0) and seen[-1] == ("Downloading the song", 1.0)
    assert download(f"{base}/Moonlight.wav").path == got.path  # downloading again replaces it


def test_a_page_without_a_song_is_explained(site):
    root, base = site
    (root / "page.html").write_text("<html><head><title>Hi</title></head><body>No music here</body></html>")
    with pytest.raises(LinkError, match="can't find a song"):
        download(f"{base}/page.html")
    with pytest.raises(LinkError, match="404"):
        download(f"{base}/missing.mp3")


def test_an_unreachable_site_is_explained(site):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # nothing listens here once the socket is closed
    with pytest.raises(LinkError, match="Couldn't reach the site"):
        download(f"http://127.0.0.1:{port}/song.mp3")


def test_cli_converts_a_link(site, tmp_path):
    root, base = site
    write_midi(root / "Tune.mid", [{"name": "Piano", "program": 0, "notes": [(60, 0, 1, 90), (64, 1, 1, 90)]}])
    out = tmp_path / "scripts"
    out.mkdir()
    assert cli.main(["convert", f"{base}/Tune.mid", "-o", str(out)]) == 0
    assert (tmp_path / "downloads" / "Tune.mid").exists()
    script = read_script(out / "Tune.apno")
    assert script.meta.title == "Tune"
    assert [n.pitch for n in script.notes] == [60, 64]
    assert cli.main(["convert", f"{base}/nothing.mid"]) == 1
