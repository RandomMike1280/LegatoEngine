# LegatoEngine

LegatoEngine turns a song into its own playable script and plays it on Roblox pianos.

Most Roblox auto-players replay a Virtual Piano sheet that someone already wrote. LegatoEngine starts from the original song instead:

1. **You give it a song:** a full song with vocals and a band, a recording of one instrument (piano, guitar…), a MIDI file, or a link to one (YouTube, SoundCloud…).
2. **It works out the notes:** it separates the instruments, finds the melody, bass line and chords, and arranges them so they fit on a 61-key (or 88-key) Roblox piano.
3. **It saves an `.apno` script:** an encrypted file of its own with the chords, keys and timing. Only LegatoEngine can read it.
4. **It plays the script in Roblox:** it presses the keys for you, with millisecond timing, using Shift for black keys and Ctrl for the 88-key extras.

It runs on Apple Silicon Macs (macOS 13 or later). On Windows, its command line converts songs ([Converting on Windows](#converting-on-windows)) and [LegatoPlayer](#legatoplayer-for-windows-and-intel-macs) plays the scripts.

LegatoEngine was called AutoPiano at first. The first time it starts, it moves `~/Music/AutoPiano`, its cache and its downloaded models to folders with the new name and keeps your settings. Scripts made before the rename still open.

## Setup

```bash
brew install uv ffmpeg deno
git clone https://github.com/RandomMike1280/LegatoEngine.git
cd LegatoEngine
uv sync
```

`uv sync` installs Python 3.12 and every dependency into `.venv`, including yt-dlp, which downloads songs from links. ffmpeg reads the formats that libsndfile can't, such as `.m4a` and `.aac`, which most downloaded songs are. Deno is only needed for YouTube links: YouTube only hands its audio to players that run its JavaScript. The models:

| Model | Used for | Where it's kept |
| --- | --- | --- |
| BS-RoFormer-SW (6 stems) | separating vocals, bass, piano, guitar, other and drums | `~/Library/Application Support/LegatoEngine/models`, downloaded (699 MB, checked against its SHA-256) the first time a song is separated. Its weights come from Hugging Face mirrors and don't state a licence. The model code is vendored from [ZFTurbo's Music-Source-Separation-Training](https://github.com/ZFTurbo/Music-Source-Separation-Training) (MIT). On Apple Silicon it runs through our port to Apple's [MLX](https://github.com/ml-explore/mlx) (MIT), from a half-precision copy of the weights made next to them the first time (351 MB). |
| Transkun V2 | turning the piano part of a full song, and solo recordings, into notes | inside the `transkun` package |
| MuScriptor (medium) | turning the bass, guitar and other parts of a full song into notes | `~/Library/Application Support/LegatoEngine/models/MuScriptor-medium`, taken from Hugging Face (1.2 GB, checked against its SHA-256) the first time a full song is converted. The code is MIT; **the weights are CC BY-NC 4.0, for non-commercial use only**, and gated: see below. |
| SwiftF0 | following the sung melody (and the bass line, when MuScriptor can't be used) | inside the `swift-f0` package (MIT), run by ONNX Runtime |

MuScriptor's weights can only be downloaded by a Hugging Face account that accepted the model's conditions. Once per Mac: make a free account, accept the conditions at <https://huggingface.co/MuScriptor/muscriptor-medium>, then sign in from Terminal:

```bash
uvx --from huggingface_hub hf auth login
```

Without it, full songs still convert, the way they did before MuScriptor: SwiftF0 follows the bass line and Transkun transcribes the guitar and other parts too. The progress line then says the instrument model couldn't be downloaded, and the result isn't cached, so the next conversion tries again.

## Run it

```bash
uv run legatoengine
```

### Allow LegatoEngine to press keys

macOS only lets an app press keys in other apps if it has the **Accessibility** permission. Until it has it, LegatoEngine shows a banner. Converting, listening and Test mode all work without it.

1. Click **Allow…** in the banner, or open **System Settings → Privacy & Security → Accessibility**.
2. Turn on the app that runs LegatoEngine:
   - if you started it with `uv run legatoengine`, turn on your terminal app (Terminal, iTerm…)
   - if you use the packaged app, turn on **LegatoEngine**
3. The banner disappears by itself within a couple of seconds.

The same permission lets LegatoEngine hear its hotkeys while Roblox is in front, and hide them from the game. Without it, hotkeys still work if the app has **Input Monitoring**, but the game also sees the key.

## Converting a song (Convert tab)

1. Drop a song on the box, or click it to choose one. MIDI files convert instantly. On an M1 Pro, a solo piano recording takes about 8 seconds per minute of audio (Auto-detect adds about 8 seconds, to separate three stretches of the song first), and a full song about 0.8 times as long as it lasts. A conversion takes at most about 3.5 GB of memory (Activity Monitor's Memory column, which counts the GPU's share too), because each model is freed before the next one loads. The first Full song or Auto-detect conversion also downloads the separation model (699 MB), and the first full song the instrument model (1.2 GB).

   Or paste a link into the field under the box, or drag one there from your browser: YouTube, SoundCloud, Bandcamp, most other video and music sites, or a direct link to an audio or MIDI file. **Convert** downloads the song first, into `~/Music/LegatoEngine/Downloads`, and then converts it as usual. Converting it again, for example as another **Type**, uses the downloaded file. Piano covers convert much better than the original songs, so look for one first.
2. Check **Type**. *Auto-detect* tells a full song from a solo instrument by how its energy splits across the separated parts of three stretches of the song. You can set it yourself if it guesses wrong.
3. Shape the arrangement. It updates instantly, because the transcription is cached.

| Setting | Choices |
| --- | --- |
| **Style** | **Full**: every part, up to 8 keys at once. **Simplified**: melody, bass and lighter chords, up to 4 keys. **Melody + bass**. **Melody only**. |
| **Piano** | **61 keys**: the standard Roblox piano. **88 keys**: the extra low and high keys are played with Ctrl. Pick the mode your game's piano is set to. |
| **Key** | **Easiest key**: moves the song by up to 6 semitones so it needs as few black keys (Shift presses) as possible. **Original key**. **Custom**. |
| **At most** | The most keys pressed at once. |
| **Snap to beat** | Pulls chords onto the beat grid, from slightly to fully. Useful for loose recordings. |

4. Click **▶ Listen** to hear the result on a built-in lofi felt piano. Click **Save to Library** to save it to `~/Music/LegatoEngine`.

The piano roll colors the melody orange, the bass blue and the chords grey. Scroll sideways to move through the song. Use ⌘-scroll or a pinch to zoom.

**Listen** works the same way on the Convert, Play and Edit tabs:

- While it plays, the button turns into **❚❚ Pause**, then **▶ Continue**. **Space** does the same anywhere in the window, except while you're typing in a field. It never presses a button, so it can't start ▶ Play.
- **■** stops. The next Listen starts from the beginning: in the Play tab, from where Play would start, and in the Edit tab, from the playhead.
- **Sustain** lets every note ring on after its key is let go, as if the sustain pedal were held down, like a Roblox piano with its sustain switch on. It only changes what you hear, and LegatoEngine remembers it. Switched mid-song, it carries on from the same spot.

### Converting many songs

Paste several links into the link field at once, or drop several songs or links on the window, and they go to the **Queue** under the piano roll. The pasted text can be anything that contains links, such as a list, a Markdown table or a whole web page; LegatoEngine picks out the links and skips repeats.

The queue converts one song at a time with the **Type** and **Arrangement** settings that are set when that song starts. Each finished song is saved straight into the library folder chosen under **Save into**, or a new one made with **New Folder…**. A script that's already there is never replaced: the new one is saved as "Title (2)". For piano covers, set **Type** to *Piano (or one instrument)*, which is faster and cleaner than *Auto-detect*.

- **Stop** halts the song being converted. **Start** begins it again later. Adding more songs starts the queue too.
- A failed song stays in the list in red with the reason. **Retry Failed** tries those songs again; a link that was already downloaded isn't downloaded again.
- Select songs and press Delete, or click **Remove**, to take them off the queue. **Clear Converted** removes the finished ones.
- Double-click a converted song to open it in the Play tab.
- The queue waits while you convert a song yourself above it, and remembers what's left when you quit.

## Playing in Roblox (Play tab)

1. In Roblox, sit at the piano first, and make sure the chat box isn't selected.
2. In LegatoEngine, pick a script. To start partway in, click the piano roll.
3. Click **▶ Play**. LegatoEngine brings Roblox to the front and counts down (3 s by default), then plays.
4. Control it with the hotkeys while Roblox is in front:
   - **F6** starts, pauses and resumes. Starting from a hotkey skips the long countdown.
   - **F7** stops.
   - On a MacBook keyboard, hold **fn** with the F-key.
   - You can choose other hotkeys. They never overlap the piano keys.

Every way playback ends (finishing, Stop, pausing, quitting, an error) lets go of all keys first, so nothing stays stuck down.

| Option | What it does |
| --- | --- |
| **Speed** | 25–200%. |
| **Hold keys** | **For each note's length**: sustains like a real player. **Tap**: lets go right away, for games that ignore key length. |
| **Keyboard-possible mode** | Only presses chords a real keyboard can: no chord mixes lowercase keys with capitals (Shift) or with Ctrl keys. Each chord keeps the melody's kind of key. A note that needs the other kind is played an octave away (88-key Ctrl notes), swapped for a copy of another note in the chord, or left out. The piano roll and **Listen** show the result, and the note beside the switch says how many chords changed. Your script file isn't touched. |
| **Test mode** | Plays without pressing any keys and reports how many presses it would have sent. |

### Finding a song

The library lists every script in `~/Music/LegatoEngine`, including the folders inside it. A script in a folder shows the folder's name, such as **Classical**. New, changed and removed scripts show up by themselves.

Type in **Search your library** to narrow the list as you type. You can search by:
- **name:** any part of the name, such as `fur elise`
- **folder:** such as `classical`
- **key:** such as `a minor`
- **piano size:** `88` finds scripts for the 88-key piano

Every word you type has to match. The search ignores case, accents (`fur` finds “Für”), punctuation and spacing (`bwv846` finds “BWV 846”). It also forgives small typos: `moonlite` finds “Moonlight”.

| Key | What it does |
| --- | --- |
| **⌘F** | Jumps to the search box from any tab. |
| **↑ ↓** | Open the next or previous result while you keep typing. |
| **Return** | Opens the best match. |
| **Esc** | Clears the search. |

The menu next to the count sorts the list by newest, name or length. While you search, the best matches come first.

## Editing a script (Edit tab)

Pick a script in the Play tab and press **Edit**, or click **Open…** in the Edit tab.

| Change | What it does |
| --- | --- |
| **Trim** | Cuts off everything before **Start** and after **End**. Drag the edges on the piano roll, type the times, or press **Here** to use the playhead. Click the roll to move the playhead. When you pause or stop **Listen**, the playhead stays there. **Trim the silence** cuts to the first and last notes. |
| **Transpose** | Moves every note up or down, by up to 24 semitones. Notes that leave the piano's range move back in by octaves. When two notes of a chord end up on the same key (such as C and C♯), the less important one is dropped. |
| **Tempo** | 25–400%. Unlike **Speed** in the Play tab, this changes the script itself. A key always gets 20 ms between presses, so at high tempos the fastest repeated notes lose a little length or, rarely, a note. |
| **Play** | Keeps or leaves out the melody, bass and chords. |
| **At most** | Lowers the most keys pressed at once. The melody and bass are kept first. |
| **Piano** | Moves the script to the other piano. A script made for 88 keys folds its extra notes into the 61-key range. |

The piano roll keeps the script's own timeline, with the trimmed parts shaded. **▶ Listen** plays the edited version at its new tempo. Every change starts from the script as you opened it, so you can change or undo them in any order. **Reset** goes back to the start.

**Save to Library** saves the result under its **Name**. If a script with that name already exists, including the one you're editing, LegatoEngine asks first, then moves the old one to the Trash, so it can be put back. `legatoengine-cli info` lists the edits a script has had.

## Command line

```bash
uv run legatoengine-cli convert song.mp3 --style simplified       # saves to ~/Music/LegatoEngine
uv run legatoengine-cli convert song.mid --key original --piano vp88 -o ~/Desktop/
uv run legatoengine-cli convert "https://www.youtube.com/watch?v=…" --type piano
uv run legatoengine-cli edit "~/Music/LegatoEngine/My Song.apno" --start 0:12 --end 1:40 --transpose -2 --tempo 110
uv run legatoengine-cli info "~/Music/LegatoEngine/My Song.apno"
uv run legatoengine-cli search fur elise                          # find scripts in your library
uv run legatoengine-cli search --sort name                        # list every script by name
uv run legatoengine-cli play "~/Music/LegatoEngine/My Song.apno" --focus-roblox
uv run legatoengine-cli play "My Song.apno" --dry-run --speed 2     # print the keys instead of pressing them
uv run legatoengine-cli play "My Song.apno" --possible              # keyboard-possible mode
```

`uv run legatoengine-cli <command> --help` lists every option. `-o` takes a file name or a folder; end it with `/` to have a new folder made. `edit` saves next to the script as "<title> (edited)" unless you give `--title` or `-o`, and it only replaces an existing file with `--force`. `search` prints each match with its path, best first, and exits with status 1 when nothing matches. While `play` runs, F6 pauses and resumes, and F7 or Ctrl-C stops.

### Checking that keys arrive correctly

```bash
uv run legatoengine-cli keytest
```

This opens a small window and plays a short test passage into it with real key presses. The passage covers single keys, Shift keys, mixed chords, fast re-presses of the same key and a quick run. The test then checks that exactly the right characters arrived (for example `!` for Shift+1 and `T` for Shift+T), and reports how close each key landed to its scheduled time. It needs the Accessibility permission for your terminal. It assumes the US/ABC keyboard layout with Caps Lock off.

## Converting on Windows

On a 64-bit Windows PC, `legatoengine-cli` converts songs, links and MIDI files into the same `.apno` scripts as on a Mac. The window and the key presses are macOS-only so far, so play the scripts with [LegatoPlayer](#legatoplayer-for-windows-and-intel-macs). **This hasn't been run on a real Windows PC yet.** It has only been checked on the Mac, by converting with the macOS parts, MLX and the GPU turned off.

1. Install uv, ffmpeg and Deno (Deno is only for YouTube links) from PowerShell, then open a new terminal so they're on PATH:

   ```powershell
   winget install astral-sh.uv
   winget install Gyan.FFmpeg
   winget install DenoLand.Deno
   ```

2. Copy the project folder over, then in it:

   ```powershell
   uv sync
   uvx --from huggingface_hub hf auth login
   uv run legatoengine-cli convert song.mp3
   ```

   `uv sync` installs PyTorch built for NVIDIA GPUs (CUDA 13.2), a download of about 3 GB. The sign-in is for MuScriptor, the same as on a Mac (see [Setup](#setup)). Scripts go to `Music\LegatoEngine`, and the cache and models to `%LOCALAPPDATA%\LegatoEngine`.

- **GPU:** an NVIDIA GeForce GTX 16 or RTX 20 series card or newer, with an up-to-date driver. Going by the memory a conversion takes on a Mac, about 4 GB of video memory should be enough, but that hasn't been measured on a PC. Older NVIDIA cards (CUDA 13 dropped them) and AMD or Intel GPUs fall back to the CPU, which is much slower: on an M1 Pro's CPU, a 40-second clip of a full song took 149 s (34 s on its GPU), and its notes came out the same.
- **Separation** runs in PyTorch at full precision there, since MLX is for Apple Silicon only. Its stems differ slightly from the Mac's, so the notes can too.
- Everything else on the command line works as on a Mac, except `play` (only `--dry-run`) and `keytest`, which need macOS to press keys.

## Building LegatoEngine.app

```bash
packaging/build_app.sh
```

This builds `dist/LegatoEngine.app`, about 1.3 GB because it includes PyTorch, MLX, ONNX Runtime and MuScriptor's code (its weights stay in the models folder), and signs it ad hoc. Move it to `/Applications` if you like. Once installed:

- You can double-click `.apno` scripts to open them.
- You can drop songs on the Dock icon.
- The app logs to `~/Library/Logs/LegatoEngine/LegatoEngine.log`.

The packaged app needs its own Accessibility permission. An ad hoc signature changes with every build, so after rebuilding, remove LegatoEngine from the Accessibility list and add it again. On another Mac, macOS blocks the first launch because the app isn't notarized. Allow it under **System Settings → Privacy & Security → Open Anyway**.

## LegatoPlayer for Windows and Intel Macs

Converting needs this Apple Silicon app or, on Windows, its [command line](#converting-on-windows), but playing finished scripts doesn't. [`player-app/`](player-app/README.md) is a small separate player for Windows and for any Mac, Apple Silicon or Intel. It has the Play tab's library, piano roll, hotkeys and options, presses exactly the same keys as the Play tab, and is about 15 MB. `player-app/packaging/build.sh` builds both downloads from this Mac.

## Making a release

```bash
packaging/release.sh
```

This builds LegatoEngine.app and both LegatoPlayer downloads, then puts these in `release/`, which git ignores:

| File | What it is |
| --- | --- |
| `LegatoEngine-mac.zip` | `LegatoEngine.app`, for Apple Silicon Macs |
| `LegatoPlayer-mac.zip` | LegatoPlayer for Apple Silicon and Intel Macs |
| `LegatoPlayer-windows.zip` | LegatoPlayer for 64-bit Windows |
| `LegatoEngine-source.zip` | the source the apps were built from, uncommitted changes included, for building it yourself |
| `SHA256SUMS.txt` | a SHA-256 checksum for each zip |

## The `.apno` format

```
"APNO" | version u16 | flags u16 | salt (16 B) | nonce (12 B) | length u32 | AES-256-GCM( zlib( msgpack(payload) ) )
```

- **Payload:**
  - the metadata: title, source file hash, length, tempo, key and transposition, piano layout, style and settings, converter version, date
  - the beat grid and sustain-pedal events
  - the notes, stored as columns: start-time deltas in ms, durations, pitches, velocities, parts (melody/bass/chords), chord numbers, physical keys, modifiers
- **Encryption:** the key is derived with HKDF-SHA256 from a secret built into LegatoEngine and a random salt per file. The header is authenticated together with the data, so a changed or damaged file is rejected instead of half-played. The format version lets newer LegatoEngine versions keep reading old scripts.
- **Limitation:** the secret ships inside the program, so this stops copying, reading and hand-editing scripts. It is not DRM that could stop someone who reverse-engineers the app.

## How it works

| Stage | Modules | What happens |
| --- | --- | --- |
| Download | `ingest/download.py` | yt-dlp fetches the best audio-only version of a link (m4a when there is one), with Deno solving YouTube's JavaScript. Playlists and live streams are refused. |
| Read | `ingest/midi.py`, `ingest/audio.py` | MIDI is read directly, skipping drums and using track names to find the melody and bass. Audio is decoded with libsndfile or ffmpeg. |
| Separate | `ingest/separate.py`, `ingest/bs_roformer/`, `ingest/bs_roformer_mlx.py` | BS-RoFormer-SW splits a full song into vocals, bass, piano, guitar, other and drums, 13.35 seconds at a time. It runs on the GPU in MLX at half precision, about twice as fast as PyTorch on MPS, which takes over for any stretch MLX can't do. The notes it leads to differ from PyTorch's less than PyTorch's own CPU and GPU results differ from each other. On 40 test songs with known notes, the bass scored 0.74 instead of 0.54 (note F1) and the chords 0.50 instead of 0.41 compared with Demucs, which it replaced, close to what perfectly separated parts would give. |
| Transcribe | `ingest/transcribe_mono.py`, `ingest/transcribe_multi.py`, `ingest/transcribe_poly.py` | SwiftF0 follows the sung melody, and splits it into notes at pitch changes, gaps and re-sung syllables. MuScriptor, a language model that writes down each note it hears with its instrument, 5 seconds at a time, transcribes the bass stem (as a bass) and the guitar and other stems together. On 40 test songs it scored 0.88 on the bass against SwiftF0's 0.82 (note F1), and with Transkun on the piano stem the chords scored 0.65 against 0.50 for Transkun on all three stems; given every part at once it misses notes, which is why the piano stays with Transkun. It doesn't say how hard a note is played, so velocities come from the stem's loudness. Without MuScriptor, SwiftF0 also follows the bass line: it hears down to 46.9 Hz, two semitones above a bass guitar's open E, so the bass is also played to it at double speed (an octave up), and that pass fills in the notes below its range. Transkun V2 on the GPU (MPS) transcribes the piano stem and solo recordings. It judges each note as a whole, from key down to key up, so a held note stays one press and a re-struck one stays two, and it holds up in echoey, noisy or phone-quality recordings. Before either model listens, the music's tuning is measured: audio that isn't at A440 (old pianos, A=432 recordings, sped-up videos) is retuned for Transkun and MuScriptor, and SwiftF0's pitches are shifted to match. Results are cached per file. |
| Arrange | `arrange/` | Assigns parts (top voice = melody, lowest = bass), then removes ghost notes (and, in piano recordings, overtones), detects the key, picks the easiest transposition, folds notes into the piano's range, groups chords, thins them to the style's limit (melody first, then bass, then the chord tones that add something new), and keeps a gap before any key is pressed again. |
| Edit | `arrange/edit.py` | Trims, transposes and retimes a finished script, then repeats the arranger's last steps: octave folding, one note per key in each chord, and the gap before a key is pressed again. |
| Play | `player/` | Turns notes into key presses: plain keys first, then Shift+black keys, then Ctrl+extra keys, 1 ms apart, with no plain key ever pressed while Shift is held. A real-time thread (`mach_wait_until`) sends them through Quartz with sub-millisecond accuracy. |

Key layouts live in `src/legatoengine/layouts/*.json`. The 88-key Ctrl mapping follows the usual Roblox 88-key convention, but it hasn't been checked in every game. Try it in yours and correct `vp88.json` if a game differs.

## Limitations

- Transcribing a full song is approximate. It works best when the vocals are clear and sung, and the accompaniment has piano or guitar. Rap, heavy distortion, or very dense mixes produce rougher scripts. Use **Simplified** or **Melody + bass** for those, or start from a MIDI file when one exists.
- A repeated note played softer than the same note still ringing becomes one longer note. On a Roblox piano every press is full volume, so these soft repeats would otherwise stand out.
- Some links can't be downloaded: private or age-restricted videos, and anything that needs signing in. Download only songs you're allowed to use. Some sites' terms don't allow downloading.
- YouTube changes often, and older yt-dlp versions stop working with it. If YouTube links fail, update yt-dlp with `uv lock --upgrade-package yt-dlp && uv sync`, then rebuild the app if you use the packaged one.
- The keys assume the US/ABC key positions, which is what Roblox piano games expect.
- Some games don't allow auto-players. Check the rules of the game you play in.

## Tests

```bash
uv run pytest -m "not slow"   # quick: layouts, format, timing, player, MIDI, arrangement, editing, downloads, CLI
uv run pytest                 # everything, including the model tests (downloads the separation model the first time)
```

The download tests use a small web server on your Mac, so they don't need the internet. The MuScriptor model test is skipped until its weights are in the models folder.
