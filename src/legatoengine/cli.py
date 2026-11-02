"""Command-line tools: convert songs, inspect and play scripts, and test real key presses.

    legatoengine-cli convert song.mp3 --style simplified
    legatoengine-cli convert "https://www.youtube.com/watch?v=…" --type piano
    legatoengine-cli edit "My Song.apno" --start 0:12 --end 1:40 --transpose -2 --tempo 110
    legatoengine-cli info "My Song.apno"
    legatoengine-cli search moonlight sonata
    legatoengine-cli play "My Song.apno" --dry-run
    legatoengine-cli keytest
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .paths import move_old_folders

PERMISSION_HELP = (
    "LegatoEngine can't press keys yet. macOS needs the Accessibility permission for the app that runs it:\n"
    "System Settings → Privacy & Security → Accessibility → turn on your terminal app (Terminal, iTerm, …),\n"
    "then run this again."
)
NO_KEYS_HELP = (
    "Pressing keys only works on macOS so far. On Windows, play scripts with LegatoPlayer\n"
    "(player-app in the project folder), or check one with: legatoengine-cli play song.apno --dry-run"
)


def main(argv: list[str] | None = None) -> int:
    from .arrange.pipeline import PRESETS
    from .layout import list_layouts
    from .library import SORTS

    parser = argparse.ArgumentParser(prog="legatoengine-cli", description="Turn songs into LegatoEngine scripts and play them.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    c = sub.add_parser("convert", help="turn a song (audio, MIDI or a link) into an .apno script")
    c.add_argument("song", help="an audio file (mp3, wav, m4a, flac, …), a MIDI file, or a link (YouTube, SoundCloud, …)")
    c.add_argument("-o", "--output", help="file or folder to save to (default: ~/Music/LegatoEngine)")
    c.add_argument("--type", choices=["auto", "full", "piano", "midi"], default="auto",
                   help="auto (default), full (a song with vocals and band), piano (one instrument), midi")
    c.add_argument("--style", choices=list(PRESETS), default="full", help="how much to play (default: full)")
    c.add_argument("--piano", choices=[layout.id for layout in list_layouts()], default="vp61",
                   help="vp61 (61 keys, default) or vp88 (88 keys)")
    c.add_argument("--key", default="auto", help='"auto" (fewest black keys, default), "original", or semitones such as -2')
    c.add_argument("--max-keys", type=int, default=0, help="most keys pressed at once (default: from the style)")
    c.add_argument("--snap", type=float, default=0.0, help="0 to 1: how strongly chords snap to the beat (default 0)")
    c.add_argument("--title", help="the script's name (default: from the file name or the video's title)")
    c.add_argument("--no-cache", action="store_true", help="transcribe again even if this song was done before")

    e = sub.add_parser("edit", help="trim a script, move it up or down, change its tempo, …")
    e.add_argument("script")
    e.add_argument("--start", default="0", help="cut everything before this time: seconds or m:ss (default 0)")
    e.add_argument("--end", help="cut everything after this time: seconds or m:ss (default: keep the end)")
    e.add_argument("--transpose", type=int, default=0, help="semitones up (such as 2) or down (such as -3)")
    e.add_argument("--tempo", type=float, default=100, help="tempo in percent: 120 plays 20%% faster (default 100)")
    e.add_argument("--drop", action="append", default=[], choices=["melody", "bass", "chords"],
                   help="leave out a part; repeat it to leave out more")
    e.add_argument("--max-keys", type=int, default=0, help="most keys pressed at once (default: unchanged)")
    e.add_argument("--piano", choices=[layout.id for layout in list_layouts()], help="move the script to the other piano")
    e.add_argument("--title", help='the new name (default: the old one with "(edited)")')
    e.add_argument("-o", "--output", help="file or folder to save to (default: next to the script)")
    e.add_argument("--force", action="store_true", help="replace the output file if it already exists")

    i = sub.add_parser("info", help="describe a script")
    i.add_argument("script")

    f = sub.add_parser("search", help="find scripts in your library by name, folder or key")
    f.add_argument("query", nargs="*", help="words to look for, such as fur elise (default: list every script)")
    f.add_argument("--sort", choices=list(SORTS), default="newest",
                   help="newest (default), name or length; matches still come best first")

    p = sub.add_parser("play", help="play a script by pressing keys")
    p.add_argument("script")
    p.add_argument("--dry-run", action="store_true", help="print the keys instead of pressing them")
    p.add_argument("--speed", type=float, default=1.0, help="playback speed, 0.25 to 4 (default 1)")
    p.add_argument("--countdown", type=float, help="seconds to wait before the first key (default 3; 0 in dry runs)")
    p.add_argument("--start", type=float, default=0.0, help="start this many seconds into the song")
    p.add_argument("--hold", choices=["natural", "tap"], default="natural",
                   help="natural holds keys for each note's length (default); tap lets go right away")
    p.add_argument("--possible", action="store_true",
                   help="keyboard-possible mode: no chord mixes plain keys with Shift or Ctrl ones")
    p.add_argument("--focus-roblox", action="store_true", help="bring Roblox to the front first")

    k = sub.add_parser("keytest", help="press real keys into a test window and check that the right characters arrive")
    k.add_argument("--speed", type=float, default=1.0, help="playback speed (default 1)")

    args = parser.parse_args(argv)
    commands = {"convert": _convert, "edit": _edit, "info": _info, "search": _search, "play": _play, "keytest": _keytest}
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130


def _fail(message: str) -> int:
    print(f"legatoengine-cli: {message}", file=sys.stderr)
    return 1


def _output_path(output: str, name: str) -> Path:
    """-o names a file, or a folder if it is one already or ends with a slash (it's made if needed)."""
    out = Path(output).expanduser()
    return out / name if out.is_dir() or output.endswith(("/", os.sep)) else out


def _status(text: str, final: bool = False) -> None:
    """One updating status line on a terminal; elsewhere only the final lines are written."""
    if sys.stderr.isatty():
        print(f"\r\x1b[K{text}", end="\n" if final else "", file=sys.stderr, flush=True)
    elif final:
        print(text, file=sys.stderr, flush=True)


# ---- convert


class _ProgressLine:
    """Conversion progress on one updating line, or one line per stage when output isn't a terminal."""

    def __init__(self, stream=sys.stderr):
        self.stream = stream
        self.tty = stream.isatty()
        self._last: tuple[str, int] | None = None

    def __call__(self, label: str, fraction: float) -> None:
        now = (label, int(fraction * 100))
        if now == self._last:
            return
        if self.tty:
            self.stream.write(f"\r\x1b[K{label}… {now[1]}%")
            self.stream.flush()
        elif self._last is None or label != self._last[0]:
            print(f"{label}…", file=self.stream, flush=True)
        self._last = now

    def end(self) -> None:
        if self.tty and self._last is not None:
            self.stream.write("\r\x1b[K")
            self.stream.flush()


def _convert(args) -> int:
    import os

    os.environ.setdefault("MPLBACKEND", "Agg")  # a dependency imports matplotlib; keep it off the screen
    from .arrange.pipeline import ArrangeError, ArrangeSettings, arrange
    from .format.apno import EXTENSION, write_script
    from .ingest.convert import load_song
    from .ingest.download import LinkError, download, is_link
    from .paths import LIBRARY_DIR, safe_filename

    link = is_link(args.song)
    if not link and not Path(args.song).is_file():
        return _fail(f"no such file: {args.song}")
    try:
        transpose = args.key if args.key in ("auto", "original") else int(args.key)
    except ValueError:
        return _fail(f'--key must be "auto", "original" or a number of semitones, not {args.key!r}')
    if not 0 <= args.snap <= 1:
        return _fail("--snap must be between 0 and 1")

    song_path, title = args.song, args.title
    if link:
        progress = _ProgressLine()
        try:
            got = download(args.song, progress=progress)
        except LinkError as e:
            progress.end()
            return _fail(str(e))
        progress.end()
        print(f"Downloaded {got.path}", file=sys.stderr)
        song_path, title = got.path, title or got.title

    progress = _ProgressLine()
    try:
        song = load_song(song_path, args.type, progress=progress, use_cache=not args.no_cache)
    except Exception as e:
        progress.end()
        if type(e).__name__ in ("AudioError", "ModelDownloadError", "ValueError"):
            return _fail(str(e))
        raise
    progress.end()
    if title:
        song.title = title
    settings = ArrangeSettings(
        preset=args.style, layout_id=args.piano, transpose=transpose, max_keys=args.max_keys, quantize=args.snap
    )
    try:
        script = arrange(song, settings)
    except ArrangeError as e:
        return _fail(str(e))

    name = safe_filename(script.meta.title or Path(song_path).stem) + EXTENSION
    out = LIBRARY_DIR / name if args.output is None else _output_path(args.output, name)
    out.parent.mkdir(parents=True, exist_ok=True)
    path = write_script(script, out)
    print(_describe(script))
    print(f"Saved {path}")
    return 0


# ---- edit


def _parse_time(text: str) -> float:
    """Seconds, such as "75" or "75.5", or minutes and seconds, such as "1:15.5"."""
    minutes, _, seconds = text.strip().rpartition(":")
    try:
        value = 60 * int(minutes or 0) + float(seconds)
    except ValueError:
        value = -1
    if value < 0 or (minutes and not 0 <= float(seconds) < 60):
        raise ValueError(f"times are seconds or m:ss, such as 75 or 1:15, not {text!r}")
    return value


def _edit(args) -> int:
    from .arrange.edit import PART_NAMES, EditError, Edits, edit_script
    from .format.apno import EXTENSION, ApnoError, read_script, write_script
    from .models import Role
    from .paths import safe_filename

    source = Path(args.script).expanduser()
    try:
        script = read_script(source)
        start = _parse_time(args.start)
        end = None if args.end is None else _parse_time(args.end)
    except (ApnoError, ValueError) as e:
        return _fail(str(e))
    roles = {name: role for role, name in PART_NAMES.items()}
    edits = Edits(
        start=start,
        end=end,
        transpose=args.transpose,
        tempo=args.tempo / 100,
        parts=frozenset(Role) - {roles[name] for name in args.drop},
        max_keys=args.max_keys,
        layout_id=args.piano if args.piano not in (None, script.meta.layout_id) else None,
        title=args.title or f"{script.meta.title} (edited)",
    )
    try:
        edited = edit_script(script, edits)
    except EditError as e:
        return _fail(str(e))

    name = safe_filename(edited.meta.title) + EXTENSION
    out = source.with_name(name) if args.output is None else _output_path(args.output, name)
    if out.suffix != EXTENSION:
        out = out.with_name(out.name + EXTENSION)
    if out.exists() and not args.force:
        return _fail(f"{out} already exists. Choose another --title or --output, or add --force to replace it.")
    path = write_script(edited, out)
    print(_describe(edited))
    print(f"Saved {path}")
    return 0


# ---- info


def _describe(script) -> str:
    from collections import Counter

    from .arrange.edit import Edits
    from .arrange.key import transposed_key_name
    from .arrange.pipeline import PRESETS
    from .layout import load_layout
    from .models import Modifier

    meta = script.meta
    notes = script.notes
    widest = max(Counter(n.chord for n in notes).values(), default=0)
    if meta.transpose:
        direction = "up" if meta.transpose > 0 else "down"
        key = f"{meta.key_name}, moved {direction} {abs(meta.transpose)} to {transposed_key_name(meta.key_name, meta.transpose)}"
    else:
        key = meta.key_name
    shift = sum(n.modifier is Modifier.SHIFT for n in notes)
    ctrl = sum(n.modifier is Modifier.CTRL for n in notes)
    preset = PRESETS[meta.preset].label if meta.preset in PRESETS else meta.preset
    minutes, seconds = divmod(int(meta.duration), 60)
    lines = [
        meta.title or "(untitled)",
        f"  from:    {meta.source_name or '?'} ({meta.source_kind})",
        f"  length:  {minutes}:{seconds:02d}, {len(notes)} notes in {script.chord_count} chords, up to {widest} keys at once",
        f"  key:     {key}",
        f"  piano:   {load_layout(meta.layout_id).name}, style {preset}",
        f"  keys:    {100 * shift / max(1, len(notes)):.0f}% need Shift, {100 * ctrl / max(1, len(notes)):.0f}% need Ctrl",
    ]
    for change in meta.settings.get("edits", []):
        lines.append(f"  edited:  {Edits.from_dict(change).describe() or 'saved again unchanged'}")
    if meta.created:
        made = datetime.fromtimestamp(meta.created).strftime("%Y-%m-%d %H:%M")
        lines.append(f"  made:    {made} by LegatoEngine {meta.converter_version}")
    return "\n".join(lines)


def _info(args) -> int:
    from .format.apno import ApnoError, read_script

    try:
        script = read_script(Path(args.script).expanduser())
    except (ApnoError, OSError) as e:
        return _fail(str(e))
    print(_describe(script))
    return 0


# ---- search


def _search(args) -> int:
    from .library import scan, search, sort_entries
    from .paths import LIBRARY_DIR

    query = " ".join(args.query).strip()
    entries = scan()
    if not entries:
        print(f"There are no scripts in {_home(LIBRARY_DIR)} yet.", file=sys.stderr)
        return 1
    found = search(sort_entries(entries, args.sort), query)
    for entry in found:
        details = [_clock(entry.duration), entry.key_name] if entry.readable else ["can't be read"]
        print(f"{entry.title}  ({', '.join(d for d in details if d)})")
        print(f"  {_home(entry.path)}")
    if query:
        print(f"{len(found)} of {len(entries)} scripts match “{query}”.", file=sys.stderr)
    else:
        print(f"{len(entries)} script{'s' if len(entries) != 1 else ''}.", file=sys.stderr)
    return 0 if found else 1


def _home(path: Path) -> str:
    """The path with the home folder written as ~, the way the other commands accept it."""
    home = Path.home()
    return str(Path("~") / path.relative_to(home)) if path.is_relative_to(home) else str(path)


# ---- play


def _require_key_access() -> bool:
    if sys.platform != "darwin":
        print(NO_KEYS_HELP, file=sys.stderr)
        return False
    from .player.permissions import can_send_keys, request_key_access

    if can_send_keys():
        return True
    request_key_access()  # asks macOS to add the terminal to the Accessibility list
    print(PERMISSION_HELP, file=sys.stderr)
    return False


def _play(args) -> int:
    from .format.apno import ApnoError, read_script
    from .player.engine import Player
    from .player.keyboard import DryRunKeyboard, system_keyboard
    from .player.timeline import PlaySettings, build_timeline

    try:
        script = read_script(Path(args.script).expanduser())
    except (ApnoError, OSError) as e:
        return _fail(str(e))
    if not 0.25 <= args.speed <= 4:
        return _fail("--speed must be between 0.25 and 4")
    if not 0 <= args.start < script.meta.duration:
        return _fail(f"--start must be between 0 and the song's length ({script.meta.duration:.0f} s)")
    if args.dry_run:
        keyboard = DryRunKeyboard(echo=True)
    elif _require_key_access():
        keyboard = system_keyboard()
    else:
        return 1
    countdown = args.countdown if args.countdown is not None else (0.0 if args.dry_run else 3.0)
    notes = script.notes
    if args.possible:
        from .arrange.possible import make_possible
        from .layout import load_layout

        notes, report = make_possible(notes, load_layout(script.meta.layout_id))
        print(f"Keyboard-possible mode: {report.chords} of {script.chord_count} chords changed "
              f"({report.moved} notes moved an octave, {report.doubled} swapped for another chord note, "
              f"{report.dropped} left out).", file=sys.stderr)

    if args.focus_roblox and not args.dry_run:
        from .player.focus import focus_roblox

        if not focus_roblox():
            print("Roblox isn't open, so keys go to whichever app is in front.", file=sys.stderr)

    total = script.meta.duration
    shown = {"countdown": None, "at": -1.0}

    def on_countdown(remaining: float) -> None:
        n = math.ceil(remaining)
        if n != shown["countdown"]:
            shown["countdown"] = n
            _status(f"Starting in {n}…")

    def on_position(t: float) -> None:
        if not args.dry_run and t - shown["at"] >= 0.25:
            shown["at"] = t
            _status(f"Playing {_clock(t)} / {_clock(total)}")

    player = Player(keyboard, on_countdown=on_countdown, on_position=on_position)
    player.load(build_timeline(notes, PlaySettings(speed=args.speed, hold=args.hold)), speed=args.speed)

    hotkeys = None
    if not args.dry_run:
        from .player.hotkeys import HotkeyListener

        hotkeys = HotkeyListener({"F6": player.toggle_pause, "F7": player.stop})
        if hotkeys.start():
            print("F6 pauses or resumes, F7 stops (hold fn on a MacBook keyboard). Ctrl-C also stops.", file=sys.stderr)
    print(f"{script.meta.title}: {_clock(total)}", file=sys.stderr)
    player.play(start=args.start, countdown=countdown)
    try:
        while not player.wait(0.2):
            pass
    except KeyboardInterrupt:
        player.stop()  # lets go of every key
    finally:
        if hotkeys:
            hotkeys.stop()
    finished = player.position >= player.duration - 0.05  # the timeline's end, which differs from the song's in tap mode
    _status(f"{'Finished' if finished else 'Stopped'} at {_clock(player.position)}.", final=True)
    return 0


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


# ---- keytest


def keytest_notes():
    """A short passage on the 61-key layout: single keys, Shift keys, mixed chords, quick re-presses and a fast run.

    Ctrl keys are left out on purpose: in a text box Ctrl+letter moves the cursor instead of typing.
    """
    from .arrange.pipeline import number_chords
    from .layout import load_layout
    from .models import Note

    layout = load_layout("vp61")
    events: list[tuple[float, int, float]] = []  # (start, pitch, duration)
    t = 0.0
    for pitch in (36, 37, 38, 39, 40, 41, 42, 60, 61, 62, 63, 64):  # 1 ! 2 @ 3 4 $ t T y Y u
        events.append((t, pitch, 0.1))
        t += 0.15
    for chord in ((60, 64, 67), (48, 61, 65, 70, 76), (37, 39, 42, 44)):  # plain, mixed, all Shift
        events += [(t, pitch, 0.12) for pitch in chord]
        t += 0.25
    for pitch in (60, 61, 60, 61, 60):  # one physical key, with and without Shift, quickly
        events.append((t, pitch, 0.06))
        t += 0.08
    for pitch in [72, 74, 76, 77, 79, 81, 83, 84] * 2:  # a fast scale
        events.append((t, pitch, 0.05))
        t += 0.06
    notes = []
    for start, pitch, duration in sorted(events):
        key, modifier = layout.lookup(pitch)
        notes.append(Note(pitch, round(start, 3), duration, key=key, modifier=modifier))
    number_chords(notes)
    return notes


def _keytest(args) -> int:
    if not _require_key_access():
        return 1
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

    from .player.engine import Player
    from .player.keyboard import system_keyboard
    from .player.timeline import MODIFIER_NAMES, PlaySettings, build_timeline, simulate_typing

    actions = build_timeline(keytest_notes(), PlaySettings(speed=args.speed))
    expected = simulate_typing(actions)
    expected_times = [a.time for a in actions if a.down and a.key not in MODIFIER_NAMES]
    arrivals: list[tuple[float, str, bool]] = []  # (perf_counter, text, auto-repeat)

    class Recorder(QObject):
        def eventFilter(self, obj, event) -> bool:
            if event.type() == QEvent.Type.KeyPress and event.text():
                arrivals.append((time.perf_counter(), event.text(), event.isAutoRepeat()))
            return False

    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = QWidget()
    window.setWindowTitle("LegatoEngine key test")
    label = QLabel("LegatoEngine is about to type into the box below.\nKeep your hands off the keyboard for a few seconds.")
    box = QPlainTextEdit()
    recorder = Recorder()
    box.installEventFilter(recorder)
    layout = QVBoxLayout(window)
    layout.addWidget(label)
    layout.addWidget(box)
    window.resize(560, 240)
    window.show()
    window.raise_()
    window.activateWindow()
    if app.platformName() == "cocoa":
        try:  # a process started from Terminal opens behind it; ask to come forward
            from AppKit import NSApplication

            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass

    player = Player(system_keyboard())
    player.load(actions)
    state = {"phase": "waiting", "since": time.monotonic(), "aborted": False}

    def focus_changed(app_state) -> None:
        if state["phase"] == "playing" and app_state != Qt.ApplicationState.ApplicationActive:
            player.stop()  # never type into another app
            state["aborted"] = True

    app.applicationStateChanged.connect(focus_changed)

    def tick() -> None:
        now = time.monotonic()
        if state["phase"] == "waiting":
            if window.isActiveWindow():
                box.setFocus()
                arrivals.clear()
                label.setText("Typing… keep your hands off the keyboard.")
                player.play(countdown=1.0)
                state["phase"] = "playing"
            elif now - state["since"] > 1.5:
                label.setText("Click this window to start the test.")
        elif state["phase"] == "playing" and player.wait(0):
            state["phase"], state["since"] = "settling", now
        elif state["phase"] == "settling" and now - state["since"] > 0.5:  # let the last keys arrive
            timer.stop()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(20)
    app.exec()
    player.stop()
    window.close()

    typed = "".join(text for _, text, _ in arrivals)
    if state["aborted"]:
        print("Key test stopped: the test window lost focus, so typing was halted.", file=sys.stderr)
        return 1
    if state["phase"] != "settling":
        print("Key test cancelled: the window was closed before the test finished.", file=sys.stderr)
        return 1
    if typed != expected:
        at = next((i for i, (a, b) in enumerate(zip(typed, expected)) if a != b), min(len(typed), len(expected)))
        print("Key test FAILED.")
        print(f"  expected: {expected}")
        print(f"  got:      {typed}")
        want = repr(expected[at]) if at < len(expected) else "nothing"
        got = repr(typed[at]) if at < len(typed) else "nothing"
        print(f"  first difference at character {at + 1}: expected {want}, got {got}")
        print("Common causes: Caps Lock is on, a keyboard layout other than US/ABC, or a key pressed during the test.")
        return 1
    print(f"Key test passed: all {len(expected)} characters arrived in order ({expected}).")
    if len(arrivals) == len(expected_times) > 1:
        drift = sorted(
            abs((arrival - arrivals[0][0]) - (scheduled - expected_times[0]))
            for (arrival, _, _), scheduled in zip(arrivals, expected_times)
        )
        print(
            f"Timing: each key landed within {1000 * drift[-1]:.1f} ms of its scheduled time "
            f"(median {1000 * drift[len(drift) // 2]:.1f} ms), measured in the test window."
        )
    if any(repeat for _, _, repeat in arrivals):
        print("Note: macOS auto-repeated a held key during the test.")
    return 0


def run() -> int:
    """The legatoengine-cli command. On macOS a conversion first restarts itself with
    MallocLargeCache=0, which macOS reads when a process starts: it then hands the memory of freed
    audio and model buffers straight back, instead of keeping up to about 1 GB of it on hand for
    reuse. (Windows has no such setting, and its execv starts a new process instead of replacing
    this one, so the terminal would think the conversion was over.)"""
    if sys.platform == "darwin" and sys.argv[1:2] == ["convert"] and os.environ.get("MallocLargeCache") != "0":
        os.environ["MallocLargeCache"] = "0"
        if getattr(sys, "frozen", False):
            os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # start over as the app, not as a child of it
            args = sys.argv[1:]
        else:
            args = sys.orig_argv[1:]
        sys.stdout.flush()
        os.execv(sys.executable, [sys.executable, *args])
    move_old_folders()
    if sys.platform == "win32":
        _prepare_windows_console()
    return main()


def _prepare_windows_console() -> None:
    """Output piped to a file is in the ANSI code page there, which can't write … or titles in
    most scripts, so those become ? instead of crashing. And the console in Windows 10 shows the
    escape code that redraws the progress line as text until it's told to read such codes."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel32.GetStdHandle(-12 & 0xFFFFFFFF)  # standard error, where progress goes
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass  # the progress line then shows the codes, and everything else still works


if __name__ == "__main__":
    sys.exit(run())
