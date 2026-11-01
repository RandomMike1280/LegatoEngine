# AutoPiano Player

A small app that plays finished AutoPiano scripts (`.apno`) on Roblox pianos, for Windows and for Macs with Apple Silicon or Intel chips. Converting songs into scripts still needs the full AutoPiano app on an Apple Silicon Mac, or its command line on Windows (see [Converting on Windows](../README.md#converting-on-windows)); this player only reads what they write.

It has the Play tab's features:

- **Library**: every script in `Music/AutoPiano` and the folders inside it, with the same forgiving search (accents, spacing and small typos don't matter) and sorting. You can pick another folder, open a single script, or drop one on the window.
- **Piano roll**: colored by part (melody orange, bass blue, harmony grey). Click it to start partway through.
- **Playback**: Play, Pause and Stop, speed from 25% to 200%, a countdown, held or tapped keys, bringing Roblox to the front, and a test mode that presses nothing.
- **Keyboard-possible mode**: the same rewrite as the Play tab, so every chord can be pressed on a real keyboard.
- **Hotkeys**: F6 plays or pauses and F7 stops while Roblox is in front. Both can be changed.

It is written in Rust with [egui](https://github.com/emilk/egui), so it builds into one small file per platform with nothing to install.

## Downloads

```bash
player-app/packaging/build.sh
```

This builds two zips in `player-app/dist/`, each with a short read-me:

| File | For |
|---|---|
| `AutoPiano-Player-mac.zip` | `AutoPiano Player.app`, one app for Apple Silicon and Intel Macs on macOS 10.15 or later. Signed ad hoc. |
| `AutoPiano-Player-windows.zip` | `AutoPiano Player.exe`, for 64-bit Windows 10 and 11. Needs no DLLs or installer. |

Neither is signed by Apple or Microsoft. The first launch on another computer shows a warning, and the read-mes explain how to get past it: **Open Anyway** on a Mac, **More info → Run anyway** on Windows.

Building needs:

- rustup, with the targets `aarch64-apple-darwin`, `x86_64-apple-darwin` and `x86_64-pc-windows-gnu`
- MinGW for the Windows exe: `brew install mingw-w64`

To run the player from source on this Mac, use `cargo run --release` in `player-app/`.

## How it matches the Play tab

These parts are line-for-line ports of the converter's Python code:

| Player file | Ported from |
|---|---|
| `apno.rs` | `format/apno.py` |
| `timeline.rs` | `player/timeline.py` |
| `possible.rs` | `arrange/possible.py` |
| `engine.rs` | `player/engine.py` |
| `library.rs` | `library.py` |

The key layouts are read from the converter's own `src/autopiano/layouts/*.json` when the player is compiled, so the two can't disagree.

Key presses are sent like this:

- **Mac**: through Quartz with explicit Shift and Ctrl flags, the same way as the Play tab. A real-time thread keeps the timing within a fraction of a millisecond.
- **Windows**: through `SendInput`, with both the virtual key and the scan code. The timer resolution is set to 1 ms, and each key press finishes with a short spin-wait.

## Tests

```bash
cd player-app && cargo test
```

- **`parity`**: the player turns the scripts in `tests/fixtures` into exactly the key presses, at exactly the times, that the Python player does. This covers five speed and hold settings, plus keyboard-possible mode. `tests/parity.py fixtures` regenerates the fixtures from the converter. `tests/parity.py check` compares any scripts, such as a whole library, using `cargo build --release --example dump`.
- **`engine`**: timing, pause and resume, stop releasing every key, starting inside a Shift group, and the countdown. On an M-series Mac the worst timing error over 400 fast key events is about 0.04 ms, natively and under Rosetta.
- **`window`**: drives the window offscreen. It covers the library, search, opening a script, keyboard-possible mode, and a test-mode run with pause and stop. Set `AUTOPIANO_SCREENSHOTS=<folder>` to save what the window looked like.

## Not yet checked

- The Windows build is compiled and its imports have been checked, but it hasn't been run on Windows yet. Things to try there: that key presses reach Roblox, including Shift and Ctrl notes, that the F6/F7 hotkeys work while Roblox is in front, and how accurate the timing is.
- On a Mac, the player sends exactly what the Play tab sends, but the player itself hasn't played in Roblox yet.
