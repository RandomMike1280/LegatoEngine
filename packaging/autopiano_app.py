"""Entry point for the packaged AutoPiano.app (see AutoPiano.spec).

Started with a command (`AutoPiano.app/Contents/MacOS/AutoPiano convert song.mp3`), it runs the
command-line tools instead of the window.
"""

import sys
from pathlib import Path

CLI_COMMANDS = ("convert", "edit", "info", "search", "play", "keytest", "-h", "--help")

if len(sys.argv) > 1 and sys.argv[1] in CLI_COMMANDS:
    from autopiano.cli import run as cli_run

    sys.exit(cli_run())

if sys.stderr is None or not sys.stderr.isatty():
    # A double-clicked app has no terminal; keep messages and crash reports in a log file instead.
    log_dir = Path.home() / "Library" / "Logs" / "AutoPiano"
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log_dir / "AutoPiano.log", "a", buffering=1, encoding="utf-8")

from autopiano.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
