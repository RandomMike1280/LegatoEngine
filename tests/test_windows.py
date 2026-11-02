"""What the command-line converter does differently on Windows, checked here by pretending to be it."""

import sys
from pathlib import Path

import pytest
import torch

from legatoengine import cli, paths
from legatoengine.ingest import separate
from legatoengine.ingest.audio import install_hint


def test_folders():
    home = Path("/Users/me")
    assert paths._app_folders("darwin", home, {}) == (
        home / "Library/Caches/LegatoEngine",
        home / "Library/Application Support/LegatoEngine/models",
    )
    local = Path("/Users/me/AppData/Local/LegatoEngine")
    assert paths._app_folders("win32", home, {"LOCALAPPDATA": "/Users/me/AppData/Local"}) == (local / "Cache", local / "models")
    assert paths._app_folders("win32", home, {}) == (local / "Cache", local / "models")


def test_file_names():
    title = 'AC/DC: Who? "Live" <2024> | best*'
    assert paths.safe_filename(title, windows=False) == 'AC-DC- Who? "Live" <2024> | best*'  # as before on a Mac
    assert paths.safe_filename(title, windows=True) == "AC-DC- Who- -Live- -2024- - best-"
    assert paths.safe_filename("Con", windows=True) == "_Con"
    assert paths.safe_filename("NUL.remix", windows=True) == "_NUL.remix"
    assert paths.safe_filename("Console", windows=True) == "Console"
    assert paths.safe_filename("x" * 99 + " y", windows=True) == "x" * 99  # no space before the extension
    assert paths.safe_filename("...", windows=True) == "Untitled"


def test_nvidia_gpus_come_first(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert separate.best_device() == "cuda"


def test_conversions_dont_restart(monkeypatch):
    def execv(path, args):
        raise AssertionError("Windows starts a new process for execv, and the terminal stops waiting")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("MallocLargeCache", raising=False)
    monkeypatch.setattr(cli.os, "execv", execv)
    monkeypatch.setattr(cli, "main", lambda: 0)
    monkeypatch.setattr(cli, "move_old_folders", lambda: [])
    monkeypatch.setattr(sys, "argv", ["legatoengine-cli", "convert", "song.mp3"])
    assert cli.run() == 0


def test_pressing_keys_says_where_to_play(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "win32")
    assert not cli._require_key_access()
    assert "LegatoPlayer" in capsys.readouterr().err


def test_install_hints(monkeypatch):
    assert install_hint("ffmpeg") == "brew install ffmpeg"
    monkeypatch.setattr(sys, "platform", "win32")
    assert install_hint("ffmpeg").startswith("winget install Gyan.FFmpeg")
    assert install_hint("deno").startswith("winget install DenoLand.Deno")


def test_the_window_explains_itself(monkeypatch, capsys):
    from legatoengine.gui import app

    monkeypatch.setattr(sys, "platform", "win32")
    assert app.main() == 1
    assert "legatoengine-cli convert" in capsys.readouterr().err


@pytest.mark.parametrize("output", ["out/", f"out{cli.os.sep}"])
def test_output_folders_end_in_either_slash(tmp_path, monkeypatch, output):
    monkeypatch.chdir(tmp_path)
    assert cli._output_path(output, "Song.apno") == Path("out") / "Song.apno"
