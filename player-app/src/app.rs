//! The player window: the library on the left, the chosen script's piano roll, and playback.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use eframe::egui::{self, Align2, Color32, FontFamily, FontId, Pos2, Rect, RichText, Sense, Stroke, Vec2};
use serde::{Deserialize, Serialize};

use crate::apno::{EXTENSION, read_script};
use crate::engine::{Player, State};
use crate::hotkeys::{Command, HOTKEYS, Hotkeys};
use crate::keys::Keyboard;
use crate::layout::{Layout, is_black, load_layout};
use crate::library::{Entry, Library, Sort, default_folder, search, sort_entries};
use crate::model::{Modifier, Note, Role, Script, transposed_key_name};
use crate::possible::make_possible;
use crate::timeline::{Action, PlaySettings, build_timeline};

const MELODY: Color32 = Color32::from_rgb(0xf0, 0x8c, 0x3a);
const BASS: Color32 = Color32::from_rgb(0x4a, 0x90, 0xe2);
const HARMONY: Color32 = Color32::from_rgb(0x8e, 0x9a, 0xaf);
const PLAYHEAD: Color32 = Color32::from_rgb(0xe5, 0x48, 0x4d);
const PIXELS_PER_SECOND: f32 = 80.0;
const GUTTER: f32 = 30.0; // the octave labels, which stay put while the roll scrolls
const RESCAN_EVERY: Duration = Duration::from_secs(2);
const HOTKEY_COUNTDOWN: f64 = 0.3; // a moment to let go of the hotkey before the first note

#[derive(Clone, Serialize, Deserialize)]
#[serde(default)]
struct Settings {
    folder: PathBuf,
    sort: String,
    speed: u32, // percent
    countdown: u32,
    tap: bool,
    possible: bool,
    focus_roblox: bool,
    test_mode: bool,
    hotkey_toggle: String,
    hotkey_stop: String,
    last_script: Option<PathBuf>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            folder: default_folder(),
            sort: Sort::Newest.id().into(),
            speed: 100,
            countdown: 3,
            tap: false,
            possible: false,
            focus_roblox: true,
            test_mode: false,
            hotkey_toggle: "F6".into(),
            hotkey_stop: "F7".into(),
            last_script: None,
        }
    }
}

/// What a hotkey press plays. The window keeps it current, so the hotkey handler never
/// has to wait for the window, which may be hidden behind Roblox.
#[derive(Default)]
struct Armed {
    actions: Option<Arc<Vec<Action>>>,
    speed: f64,
    start: f64,
    test: bool,
}

struct Shared {
    player: Player,
    armed: Mutex<Armed>,
    note: Mutex<String>, // put in front of the status while playing, such as "Roblox isn't open"
}

impl Shared {
    fn on_hotkey(&self, command: Command) {
        match command {
            Command::Stop => self.player.stop(),
            Command::TogglePause if self.player.state() == State::Stopped => {
                let armed = self.armed.lock().unwrap();
                let Some(actions) = armed.actions.clone() else { return };
                if !armed.test && !can_send_keys() {
                    *self.note.lock().unwrap() = "Allow key presses first: press Play in the player window. ".into();
                    return;
                }
                self.note.lock().unwrap().clear();
                let keyboard = if armed.test { Keyboard::dry_run() } else { Keyboard::system() };
                self.player.play(actions, armed.speed, armed.start, HOTKEY_COUNTDOWN, keyboard);
            }
            Command::TogglePause => self.player.toggle_pause(),
        }
    }
}

#[cfg(target_os = "macos")]
fn can_send_keys() -> bool {
    crate::mac::can_send_keys()
}

#[cfg(not(target_os = "macos"))]
fn can_send_keys() -> bool {
    true
}

fn focus_roblox() -> bool {
    #[cfg(target_os = "macos")]
    return crate::mac::focus_roblox();
    #[cfg(windows)]
    return crate::win::focus_roblox();
    #[allow(unreachable_code)]
    false
}

/// A script ready to play.
struct Loaded {
    path: PathBuf,
    script: Script,
    layout: &'static Layout,
    notes: Vec<Note>, // what Play presses: the script's notes, or their keyboard-possible version
    possible: bool,   // which of the two `notes` is
    possible_note: String,
    longest: f64, // the longest note, so drawing can skip to the visible part
}

impl Loaded {
    fn new(path: PathBuf, script: Script, possible: bool) -> Loaded {
        let layout = load_layout(&script.meta.layout_id);
        let mut loaded = Loaded {
            path,
            script,
            layout,
            notes: Vec::new(),
            possible: !possible,
            possible_note: String::new(),
            longest: 0.0,
        };
        loaded.choose_notes(possible);
        loaded
    }

    fn choose_notes(&mut self, possible: bool) {
        if possible == self.possible {
            return;
        }
        self.possible = possible;
        if possible {
            let (notes, report) = make_possible(&self.script.notes, self.layout);
            self.notes = notes;
            self.possible_note = if report.chords > 0 {
                format!("{} of {} chords changed", report.chords, self.script.chord_count())
            } else {
                "Every chord can already be pressed".into()
            };
        } else {
            self.notes = self.script.notes.clone();
            self.possible_note.clear();
        }
        self.notes.sort_by(|a, b| a.start.total_cmp(&b.start));
        self.longest = self.notes.iter().map(|n| n.duration).fold(0.0, f64::max);
    }

    fn summary(&self) -> String {
        let meta = &self.script.meta;
        let notes = &self.script.notes;
        let shifted = notes.iter().filter(|n| n.modifier != Modifier::None).count();
        let key = if meta.transpose != 0 && !meta.key_name.is_empty() {
            let direction = if meta.transpose > 0 { "up" } else { "down" };
            format!(
                "{} → {} ({direction} {})",
                meta.key_name,
                transposed_key_name(&meta.key_name, meta.transpose),
                meta.transpose.abs()
            )
        } else {
            meta.key_name.clone()
        };
        let parts = [
            format_time(meta.duration),
            key,
            format!("{} notes in {} chords", notes.len(), self.script.chord_count()),
            format!("{:.0}% need Shift/Ctrl", 100.0 * shifted as f64 / notes.len().max(1) as f64),
            self.layout.name.clone(),
        ];
        parts.into_iter().filter(|p| !p.is_empty()).collect::<Vec<_>>().join("  ·  ")
    }
}

pub fn format_time(seconds: f64) -> String {
    let seconds = seconds.max(0.0) as u64;
    format!("{}:{:02}", seconds / 60, seconds % 60)
}

pub struct App {
    settings: Settings,
    shared: Arc<Shared>,
    hotkeys: Hotkeys,
    library: Library,
    entries: Vec<Entry>,
    query: String,
    last_scan: Option<Instant>,
    loaded: Option<Loaded>,
    armed_for: Option<(PathBuf, u32, bool, bool)>, // what `Shared::armed` was built from
    start_at: f64,
    last_state: State,
    finished_note: String, // what the last test run would have pressed
    error: Option<String>,
    asking_permission: bool,
}

impl App {
    pub fn new(cc: &eframe::CreationContext<'_>, open: Option<PathBuf>) -> App {
        let settings: Settings = cc.storage.and_then(|s| eframe::get_value(s, eframe::APP_KEY)).unwrap_or_default();
        let mut app = App::build(cc, settings, true);
        if let Some(path) = open {
            app.open(&path, true);
        } else if let Some(path) = app.settings.last_script.clone().filter(|p| p.is_file()) {
            app.open(&path, false);
        }
        app
    }

    /// A window for the tests: showing `folder`, in test mode, with no countdown and no global hotkeys.
    #[doc(hidden)]
    pub fn for_tests(cc: &eframe::CreationContext<'_>, folder: PathBuf) -> App {
        let settings = Settings { folder, test_mode: true, focus_roblox: false, countdown: 0, ..Settings::default() };
        App::build(cc, settings, false)
    }

    fn build(cc: &eframe::CreationContext<'_>, settings: Settings, with_hotkeys: bool) -> App {
        add_fallback_fonts(&cc.egui_ctx);
        let shared = Arc::new(Shared { player: Player::new(), armed: Mutex::default(), note: Mutex::default() });
        let ctx = cc.egui_ctx.clone();
        shared.player.set_on_change(move || ctx.request_repaint());
        let hotkeys = if with_hotkeys {
            let for_hotkeys = shared.clone();
            let ctx = cc.egui_ctx.clone();
            let mut hotkeys = Hotkeys::start(move |command| {
                for_hotkeys.on_hotkey(command);
                ctx.request_repaint();
            });
            hotkeys.bind(&settings.hotkey_toggle, &settings.hotkey_stop);
            hotkeys
        } else {
            Hotkeys::off()
        };
        App {
            settings,
            shared,
            hotkeys,
            library: Library::default(),
            entries: Vec::new(),
            query: String::new(),
            last_scan: None,
            loaded: None,
            armed_for: None,
            start_at: 0.0,
            last_state: State::Stopped,
            finished_note: String::new(),
            error: None,
            asking_permission: false,
        }
    }

    fn state(&self) -> State {
        self.shared.player.state()
    }

    /// Loads a script; `report` says whether to tell the user when it can't be read.
    fn open(&mut self, path: &Path, report: bool) {
        if self.state() != State::Stopped {
            return;
        }
        match read_script(path) {
            Ok(script) => {
                self.loaded = Some(Loaded::new(path.to_path_buf(), script, self.settings.possible));
                self.settings.last_script = Some(path.to_path_buf());
                self.start_at = 0.0;
                self.finished_note.clear();
            }
            Err(e) if report => self.error = Some(format!("Couldn't open {}: {e}", file_name(path))),
            Err(_) => {}
        }
    }

    fn rescan(&mut self) {
        if self.last_scan.is_some_and(|t| t.elapsed() < RESCAN_EVERY) {
            return;
        }
        self.entries = self.library.scan(&self.settings.folder);
        self.last_scan = Some(Instant::now());
    }

    /// Keeps what a hotkey would play up to date with the window's settings.
    fn rearm(&mut self) {
        let Some(loaded) = &mut self.loaded else {
            self.shared.armed.lock().unwrap().actions = None;
            self.armed_for = None;
            return;
        };
        loaded.choose_notes(self.settings.possible);
        let wanted = (loaded.path.clone(), self.settings.speed, self.settings.tap, self.settings.possible);
        let mut armed = self.shared.armed.lock().unwrap();
        if self.armed_for.as_ref() != Some(&wanted) {
            let settings = PlaySettings { speed: self.settings.speed as f64 / 100.0, tap: self.settings.tap, ..Default::default() };
            armed.actions = Some(Arc::new(build_timeline(&loaded.notes, &settings)));
            armed.speed = settings.speed;
            self.armed_for = Some(wanted);
        }
        armed.start = self.start_at;
        armed.test = self.settings.test_mode;
    }

    fn play(&mut self) {
        match self.state() {
            State::Paused => return self.shared.player.resume(),
            State::Stopped => {}
            _ => return,
        }
        self.rearm();
        let armed = self.shared.armed.lock().unwrap();
        let Some(actions) = armed.actions.clone() else { return };
        let test = armed.test;
        if !test && !can_send_keys() {
            drop(armed);
            self.asking_permission = true;
            return;
        }
        let mut note = String::new();
        if !test && self.settings.focus_roblox && !focus_roblox() {
            note = "Roblox isn't open, so keys go to whichever app is in front. ".into();
        }
        *self.shared.note.lock().unwrap() = note;
        self.finished_note.clear();
        let keyboard = if test { Keyboard::dry_run() } else { Keyboard::system() };
        self.shared.player.play(actions, armed.speed, armed.start, self.settings.countdown as f64, keyboard);
    }

    fn status(&self, state: State) -> String {
        let (toggle, stop) = (&self.settings.hotkey_toggle, &self.settings.hotkey_stop);
        let note = self.shared.note.lock().unwrap().clone();
        match state {
            State::Countdown => format!(
                "{note}Starting in {}… switch to Roblox now.",
                self.shared.player.countdown_left().ceil().max(1.0)
            ),
            State::Playing => format!("{note}Playing. {toggle} pauses, {stop} stops."),
            State::Paused => format!("Paused. {toggle} or Resume carries on."),
            State::Stopped if !self.finished_note.is_empty() => self.finished_note.clone(),
            State::Stopped if !note.is_empty() && self.loaded.is_some() => note, // a hotkey couldn't start
            State::Stopped => self.idle_status(),
        }
    }

    fn idle_status(&self) -> String {
        let (toggle, stop) = (&self.settings.hotkey_toggle, &self.settings.hotkey_stop);
        if self.loaded.is_none() {
            return "Pick a script from your library.".into();
        }
        if let Some(problem) = &self.hotkeys.problem {
            return format!("Ready. {problem}");
        }
        let mut text = format!("Ready. In Roblox, press {toggle} to start or pause and {stop} to stop.");
        if cfg!(target_os = "macos") {
            if toggle.starts_with('F') || stop.starts_with('F') {
                text += " On a MacBook keyboard, hold fn with the F-key.";
            }
            if !self.settings.test_mode && !can_send_keys() {
                text += " First, press Play once to let the player press keys.";
            }
        }
        text
    }

    /// Notices the end of a run, to report a test run and put the playhead back.
    fn watch_state(&mut self, state: State) {
        if state == State::Stopped && self.last_state != State::Stopped {
            self.shared.note.lock().unwrap().clear(); // it was about that run
            let (presses, dry) = self.shared.player.last_run();
            if dry && presses > 0 {
                self.finished_note = format!("Test run finished: {presses} key presses would have been sent.");
            }
        }
        self.last_state = state;
    }

    // ---- the library

    fn library_panel(&mut self, ui: &mut egui::Ui, stopped: bool) {
        ui.add_space(6.0);
        ui.heading("Library");
        ui.add_space(2.0);
        ui.horizontal(|ui| {
            ui.label(RichText::new(self.settings.folder.display().to_string()).small().weak())
                .on_hover_text("Scripts in this folder and the folders inside it");
        });
        ui.horizontal(|ui| {
            if ui.add_enabled(stopped, egui::Button::new("Change folder…")).clicked() {
                let mut dialog = rfd::FileDialog::new().set_title("Choose your scripts folder");
                if self.settings.folder.is_dir() {
                    dialog = dialog.set_directory(&self.settings.folder);
                }
                if let Some(folder) = dialog.pick_folder() {
                    self.settings.folder = folder;
                    self.last_scan = None;
                }
            }
            if ui.button("Show folder").clicked() {
                let _ = std::fs::create_dir_all(&self.settings.folder);
                reveal(&self.settings.folder);
            }
        });
        ui.add_space(4.0);
        let search_box = ui.add_enabled(
            stopped,
            egui::TextEdit::singleline(&mut self.query).hint_text("Search titles, folders, keys…").desired_width(f32::INFINITY),
        );
        let sort = Sort::from_id(&self.settings.sort);
        let shown = sort_entries(search(&self.entries, &self.query), sort);
        if search_box.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
            if let Some(first) = shown.iter().find(|e| e.readable) {
                let path = first.path.clone();
                self.open(&path, true);
            }
        }
        ui.horizontal(|ui| {
            let count = if self.query.trim().is_empty() {
                plural(self.entries.len(), "script")
            } else {
                format!("{} of {}", shown.len(), self.entries.len())
            };
            ui.label(RichText::new(count).weak());
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.add_enabled_ui(stopped, |ui| {
                    egui::ComboBox::from_id_salt("sort")
                        .selected_text(sort.label())
                        .show_ui(ui, |ui| {
                            for option in Sort::ALL {
                                if ui.selectable_label(option == sort, option.label()).clicked() {
                                    self.settings.sort = option.id().into();
                                }
                            }
                        })
                        .response
                        .accessible_name("Sort scripts by");
                });
            });
        });
        ui.separator();
        let open_path = self.loaded.as_ref().map(|l| l.path.clone());
        let mut chosen: Option<PathBuf> = None;
        egui::Panel::bottom("library_buttons").frame(egui::Frame::NONE).show(ui, |ui| {
            ui.add_space(6.0);
            if ui.add_enabled(stopped, egui::Button::new("Open a script…")).clicked() {
                let mut dialog = rfd::FileDialog::new().add_filter("AutoPiano script", &[EXTENSION]);
                if self.settings.folder.is_dir() {
                    dialog = dialog.set_directory(&self.settings.folder);
                }
                chosen = dialog.pick_file();
            }
            ui.add_space(6.0);
        });
        egui::ScrollArea::vertical().auto_shrink([false, false]).show(ui, |ui| {
            if self.entries.is_empty() {
                ui.add_space(8.0);
                ui.label(
                    RichText::new(
                        "No scripts here yet. Convert songs with AutoPiano on a Mac, then put the .apno files in this folder \
                         (subfolders are fine) or drop them on this window.",
                    )
                    .weak(),
                );
            } else if shown.is_empty() {
                ui.add_space(8.0);
                ui.label(RichText::new("Nothing matches that search.").weak());
            }
            for entry in &shown {
                let selected = open_path.as_deref() == Some(entry.path.as_path());
                let mut details = Vec::new();
                if !entry.folder.is_empty() {
                    details.push(entry.folder.clone());
                }
                if entry.readable {
                    details.push(format_time(entry.duration));
                    if !entry.key_name.is_empty() {
                        details.push(entry.key_name.clone());
                    }
                } else {
                    details.push("can't be read".into());
                }
                let response = ui
                    .add_enabled_ui(stopped && entry.readable, |ui| {
                        library_row(ui, selected, &entry.title, &details.join("  ·  "))
                    })
                    .inner;
                if response.clicked() {
                    chosen = Some(entry.path.clone());
                }
                if !entry.readable {
                    response.on_disabled_hover_text("Made by a newer AutoPiano, or damaged.");
                }
            }
        });
        if let Some(path) = chosen {
            self.open(&path, true);
        }
    }

    // ---- now playing

    fn playing_panel(&mut self, ui: &mut egui::Ui, state: State) {
        let stopped = state == State::Stopped;
        ui.add_space(6.0);
        match &self.loaded {
            Some(loaded) => {
                let meta = &loaded.script.meta;
                let title = if meta.title.is_empty() { file_name(&loaded.path) } else { meta.title.clone() };
                ui.heading(title);
                ui.label(RichText::new(loaded.summary()).weak());
            }
            None => {
                ui.heading("Nothing selected");
                ui.label(RichText::new("Pick a script from your library, or open one.").weak());
            }
        }
        ui.add_space(4.0);
        egui::Panel::bottom("controls").frame(egui::Frame::NONE).show(ui, |ui| {
            self.transport(ui, state);
            ui.add_space(6.0);
            ui.add_enabled_ui(stopped, |ui| self.options(ui));
            ui.add_space(6.0);
        });
        egui::CentralPanel::no_frame().show(ui, |ui| self.piano_roll(ui, state));
    }

    fn transport(&mut self, ui: &mut egui::Ui, state: State) {
        let has_script = self.loaded.is_some();
        let stopped = state == State::Stopped;
        ui.add_space(6.0);
        ui.horizontal(|ui| {
            let play_text = if state == State::Paused { "▶ Resume" } else { "▶ Play" };
            if ui.add_enabled(has_script && (stopped || state == State::Paused), egui::Button::new(play_text)).clicked() {
                self.play();
            }
            let pause_text = if state == State::Paused { "Resume" } else { "Pause" };
            if ui.add_enabled(matches!(state, State::Playing | State::Paused), egui::Button::new(pause_text)).clicked() {
                self.shared.player.toggle_pause();
            }
            if ui.add_enabled(!stopped, egui::Button::new("■ Stop")).clicked() {
                self.shared.player.stop();
            }
            ui.add_space(12.0);
            let now = if stopped { self.start_at } else { self.shared.player.position() };
            let total = self.loaded.as_ref().map_or(0.0, |l| l.script.meta.duration);
            ui.label(format!("{} / {}", format_time(now), format_time(total)));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if self.start_at > 0.0 {
                    if ui.add_enabled(stopped, egui::Button::new("From the beginning").frame(false)).clicked() {
                        self.start_at = 0.0;
                    }
                    ui.label(RichText::new(format!("Starts at {}", format_time(self.start_at))).weak());
                } else if has_script && stopped {
                    ui.label(RichText::new("Click the piano roll to start from there").weak().small());
                }
            });
        });
    }

    fn options(&mut self, ui: &mut egui::Ui) {
        let s = &mut self.settings;
        egui::Frame::group(ui.style()).show(ui, |ui| {
            ui.set_width(ui.available_width());
            egui::Grid::new("options").num_columns(2).spacing([12.0, 8.0]).show(ui, |ui| {
                let label = ui.label("Speed");
                ui.add(egui::Slider::new(&mut s.speed, 25..=200).step_by(5.0).suffix("%")).labelled_by(label.id);
                ui.end_row();

                let label = ui.label("Countdown");
                ui.add(egui::Slider::new(&mut s.countdown, 0..=10).suffix(" s")).labelled_by(label.id);
                ui.end_row();

                let label = ui.label("Hold keys");
                egui::ComboBox::from_id_salt("hold")
                    .selected_text(if s.tap { "Tap (let go right away)" } else { "For each note's length" })
                    .show_ui(ui, |ui| {
                        ui.selectable_value(&mut s.tap, false, "For each note's length");
                        ui.selectable_value(&mut s.tap, true, "Tap (let go right away)");
                    })
                    .response
                    .labelled_by(label.id);
                ui.end_row();

                ui.label("");
                ui.horizontal(|ui| {
                    ui.checkbox(&mut s.possible, "Keyboard-possible mode").on_hover_text(
                        "A real keyboard can't press lowercase and capital keys at the same moment (Shift changes them all), \
                         or Ctrl keys together with normal ones. With this on, every chord sticks to one of them: the \
                         melody's, or whichever keeps the most of the chord. Each note that would need another is played \
                         an octave away, swapped for a copy of another note of the chord, or left out. The piano roll \
                         shows what will be played.",
                    );
                    if let Some(loaded) = &self.loaded {
                        if s.possible && !loaded.possible_note.is_empty() {
                            ui.label(RichText::new(&loaded.possible_note).weak());
                        }
                    }
                });
                ui.end_row();

                ui.label("");
                ui.checkbox(&mut s.focus_roblox, "Bring Roblox to the front when I press Play");
                ui.end_row();

                ui.label("");
                ui.checkbox(&mut s.test_mode, "Test mode: don't press any keys");
                ui.end_row();

                ui.label("Hotkeys");
                let mut changed = false;
                ui.horizontal(|ui| {
                    let label = ui.label("Play / pause");
                    changed |= hotkey_choice(ui, "hotkey_toggle", &mut s.hotkey_toggle, label.id);
                    ui.add_space(12.0);
                    let label = ui.label("Stop");
                    changed |= hotkey_choice(ui, "hotkey_stop", &mut s.hotkey_stop, label.id);
                });
                if changed {
                    self.hotkeys.bind(&s.hotkey_toggle, &s.hotkey_stop);
                }
                ui.end_row();
            });
        });
    }

    fn piano_roll(&mut self, ui: &mut egui::Ui, state: State) {
        let dark = ui.visuals().dark_mode;
        let (background, black_row, line, label) = if dark {
            (Color32::from_rgb(0x1e, 0x1f, 0x24), Color32::from_rgb(0x26, 0x27, 0x2d), Color32::from_rgb(0x34, 0x35, 0x3c), Color32::from_rgb(0x8a, 0x8d, 0x96))
        } else {
            (Color32::from_rgb(0xfb, 0xfb, 0xfc), Color32::from_rgb(0xf0, 0xf1, 0xf4), Color32::from_rgb(0xe1, 0xe3, 0xe8), Color32::from_rgb(0x77, 0x7b, 0x85))
        };
        let height = ui.available_height().max(140.0);
        let (low, high) = self.loaded.as_ref().map_or((36, 96), |l| (l.layout.low, l.layout.high));
        let rows = (high - low + 1) as f32;
        let row_height = (height - 8.0) / rows;
        let y_of = |top: f32, pitch: i32| top + 4.0 + (high - pitch) as f32 * row_height;
        let playing = state != State::Stopped;
        let position = if playing { Some(self.shared.player.position()) } else { (self.start_at > 0.0).then_some(self.start_at) };

        ui.horizontal_top(|ui| {
            ui.spacing_mut().item_spacing.x = 0.0;
            // octave labels
            let (gutter, painter) = ui.allocate_painter(Vec2::new(GUTTER, height), Sense::hover());
            painter.rect_filled(gutter.rect, 0.0, background);
            for pitch in low..=high {
                if pitch.rem_euclid(12) == 0 {
                    painter.text(
                        Pos2::new(gutter.rect.right() - 4.0, y_of(gutter.rect.top(), pitch) + row_height / 2.0),
                        Align2::RIGHT_CENTER,
                        format!("C{}", pitch / 12 - 1),
                        FontId::new(10.0, FontFamily::Proportional),
                        label,
                    );
                }
            }

            let duration = self.loaded.as_ref().map_or(0.0, |l| l.script.meta.duration.max(l.notes.last().map_or(0.0, |n| n.end())));
            let view_width = ui.available_width();
            let width = (duration as f32 * PIXELS_PER_SECOND + 24.0).max(view_width);
            let mut area = egui::ScrollArea::horizontal().id_salt("roll").auto_shrink([false, false]);
            if let (true, Some(t)) = (playing, position) {
                area = area.horizontal_scroll_offset((t as f32 * PIXELS_PER_SECOND - view_width / 3.0).max(0.0));
            }
            area.show_viewport(ui, |ui, viewport| {
                let (response, painter) = ui.allocate_painter(Vec2::new(width, height), Sense::click());
                let rect = response.rect;
                let visible = Rect::from_min_size(rect.min + viewport.min.to_vec2(), viewport.size());
                painter.rect_filled(visible, 0.0, background);
                for pitch in low..=high {
                    let y = y_of(rect.top(), pitch);
                    if is_black(pitch) {
                        painter.rect_filled(
                            Rect::from_min_max(Pos2::new(visible.left(), y), Pos2::new(visible.right(), y + row_height)),
                            0.0,
                            black_row,
                        );
                    }
                    if pitch.rem_euclid(12) == 0 {
                        let y = y + row_height;
                        painter.line_segment([Pos2::new(visible.left(), y), Pos2::new(visible.right(), y)], Stroke::new(1.0, line));
                    }
                }
                let Some(loaded) = &self.loaded else { return };
                let x_of = |t: f64| rect.left() + t as f32 * PIXELS_PER_SECOND;
                let (t0, t1) = (
                    ((visible.left() - rect.left()) / PIXELS_PER_SECOND) as f64,
                    ((visible.right() - rect.left()) / PIXELS_PER_SECOND) as f64,
                );
                let beats_from = loaded.script.beats.partition_point(|&b| b < t0);
                for &beat in loaded.script.beats[beats_from..].iter().take_while(|&&b| b <= t1) {
                    let x = x_of(beat);
                    painter.line_segment([Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())], Stroke::new(1.0, line.gamma_multiply(0.6)));
                }
                let first = loaded.notes.partition_point(|n| n.start < t0 - loaded.longest);
                for n in loaded.notes[first..].iter().take_while(|n| n.start <= t1) {
                    if n.end() < t0 {
                        continue;
                    }
                    let color = match n.role {
                        Role::Melody => MELODY,
                        Role::Bass => BASS,
                        Role::Harmony => HARMONY,
                    };
                    let y = y_of(rect.top(), n.pitch);
                    let note = Rect::from_min_max(
                        Pos2::new(x_of(n.start), y),
                        Pos2::new(x_of(n.end()).max(x_of(n.start) + 2.0), y + row_height.max(2.0) - 0.5),
                    );
                    painter.rect_filled(note, 1.5, color);
                }
                if let Some(t) = position {
                    let x = x_of(t);
                    painter.line_segment([Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())], Stroke::new(2.0, PLAYHEAD));
                }
                if !playing {
                    if let Some(at) = response.interact_pointer_pos().filter(|_| response.clicked()) {
                        self.start_at = (((at.x - rect.left()) / PIXELS_PER_SECOND) as f64).clamp(0.0, duration);
                    }
                    if response.hovered() {
                        ui.ctx().set_cursor_icon(egui::CursorIcon::PointingHand);
                    }
                }
            });
        });
    }

    fn permission_dialog(&mut self, ctx: &egui::Context) {
        if !self.asking_permission {
            return;
        }
        if can_send_keys() {
            self.asking_permission = false;
            return;
        }
        let modal = egui::Modal::new(egui::Id::unique("permission")).show(ctx, |ui| {
            ui.set_max_width(420.0);
            ui.heading("Allow AutoPiano Player to press keys");
            ui.add_space(6.0);
            ui.label("To play in Roblox, the player needs the Accessibility permission.");
            ui.add_space(4.0);
            ui.label(
                "In System Settings → Privacy & Security → Accessibility, turn on AutoPiano Player. \
                 Then press Play again.\n\nWant to try it first? Turn on Test mode.",
            );
            ui.add_space(10.0);
            ui.horizontal(|ui| {
                if ui.button("Open System Settings").clicked() {
                    #[cfg(target_os = "macos")]
                    {
                        crate::mac::ask_for_key_access(); // puts the player in the list, ready to switch on
                        crate::mac::open_accessibility_settings();
                    }
                    ui.close();
                }
                if ui.button("Cancel").clicked() {
                    ui.close();
                }
            });
        });
        if modal.should_close() {
            self.asking_permission = false;
        }
    }

    fn error_dialog(&mut self, ctx: &egui::Context) {
        let Some(message) = self.error.clone() else { return };
        let modal = egui::Modal::new(egui::Id::unique("error")).show(ctx, |ui| {
            ui.set_max_width(420.0);
            ui.label(message);
            ui.add_space(8.0);
            if ui.button("OK").clicked() {
                ui.close();
            }
        });
        if modal.should_close() {
            self.error = None;
        }
    }

    fn take_dropped_files(&mut self, ctx: &egui::Context) {
        let dropped: Vec<PathBuf> = ctx.input(|i| i.raw.dropped_files.iter().map(|f| f.path().to_path_buf()).collect());
        if let Some(path) = dropped.iter().find(|p| p.extension().is_some_and(|e| e == EXTENSION)) {
            self.open(path, true);
        } else if !dropped.is_empty() {
            self.error = Some(format!(
                "Only AutoPiano scripts (.{EXTENSION}) can be played here. Songs, MIDI files and links are converted \
                 by AutoPiano on a Mac."
            ));
        }
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        let state = self.state();
        self.watch_state(state);
        let stopped = state == State::Stopped;
        self.rescan();
        self.take_dropped_files(&ctx);
        self.rearm();

        egui::Panel::bottom("status").show(ui, |ui| {
            ui.add_space(4.0);
            ui.label(self.status(state));
            ui.add_space(4.0);
        });
        egui::Panel::left("library").default_size(290.0).size_range(220.0..=480.0).show(ui, |ui| {
            self.library_panel(ui, stopped);
        });
        egui::CentralPanel::default().show(ui, |ui| self.playing_panel(ui, state));
        self.rearm(); // the settings or the start may have just changed
        self.permission_dialog(&ctx);
        self.error_dialog(&ctx);
        ctx.request_repaint_after(RESCAN_EVERY);
    }

    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        eframe::set_value(storage, eframe::APP_KEY, &self.settings);
    }

    fn on_exit(&mut self) {
        self.shared.player.stop(); // lets go of every key
    }
}

/// One script in the library list: its title, and under it where it is, how long, and its key.
fn library_row(ui: &mut egui::Ui, selected: bool, title: &str, details: &str) -> egui::Response {
    let (rect, response) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 40.0), Sense::click());
    response.widget_info(|| {
        egui::WidgetInfo::selected(egui::Role::Button, ui.is_enabled(), selected, format!("{title}, {details}"))
    });
    if ui.is_rect_visible(rect) {
        let visuals = ui.style().interact_selectable(&response, selected);
        if selected || response.hovered() || response.has_focus() {
            ui.painter().rect(rect, 4.0, visuals.weak_bg_fill, visuals.bg_stroke, egui::StrokeKind::Inside);
        }
        let painter = ui.painter().with_clip_rect(rect.shrink(2.0));
        let (strong, weak) = if ui.is_enabled() {
            (visuals.text_color(), ui.visuals().weak_text_color())
        } else {
            (ui.visuals().weak_text_color(), ui.visuals().weak_text_color())
        };
        let left = rect.left() + 8.0;
        painter.text(Pos2::new(left, rect.top() + 5.0), Align2::LEFT_TOP, title, FontId::proportional(14.0), strong);
        painter.text(Pos2::new(left, rect.top() + 23.0), Align2::LEFT_TOP, details, FontId::proportional(11.0), weak);
    }
    response
}

fn hotkey_choice(ui: &mut egui::Ui, id: &str, value: &mut String, label: egui::Id) -> bool {
    let mut changed = false;
    egui::ComboBox::from_id_salt(id)
        .selected_text(value.as_str())
        .width(56.0)
        .show_ui(ui, |ui| {
            for name in HOTKEYS {
                if ui.selectable_label(value == name, name).clicked() && value != name {
                    *value = name.to_string();
                    changed = true;
                }
            }
        })
        .response
        .labelled_by(label);
    changed
}

fn file_name(path: &Path) -> String {
    path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default()
}

fn plural(n: usize, word: &str) -> String {
    format!("{n} {word}{}", if n == 1 { "" } else { "s" })
}

fn reveal(folder: &Path) {
    #[cfg(target_os = "macos")]
    let _ = std::process::Command::new("open").arg(folder).spawn();
    #[cfg(windows)]
    let _ = std::process::Command::new("explorer").arg(folder).spawn();
}

/// Lets titles in Japanese, Chinese or Korean show, using fonts the system already has.
fn add_fallback_fonts(ctx: &egui::Context) {
    #[cfg(target_os = "macos")]
    let choices: Vec<Vec<PathBuf>> = vec![
        vec!["/System/Library/Fonts/Supplemental/Arial Unicode.ttf".into()],
        vec!["/System/Library/Fonts/Hiragino Sans GB.ttc".into(), "/System/Library/Fonts/AppleSDGothicNeo.ttc".into()],
    ];
    #[cfg(windows)]
    let choices: Vec<Vec<PathBuf>> = {
        let fonts = PathBuf::from(std::env::var_os("WINDIR").unwrap_or_else(|| "C:\\Windows".into())).join("Fonts");
        vec![vec![fonts.join("msgothic.ttc"), fonts.join("msyh.ttc"), fonts.join("malgun.ttf")]]
    };
    #[cfg(not(any(target_os = "macos", windows)))]
    let choices: Vec<Vec<PathBuf>> = Vec::new();

    // the first set of which any font exists
    let Some(set) = choices.into_iter().find(|set| set.iter().any(|p| p.is_file())) else { return };
    let mut fonts = egui::FontDefinitions::default();
    for path in set {
        let Ok(bytes) = std::fs::read(&path) else { continue };
        let name = file_name(&path);
        fonts.font_data.insert(name.clone(), Arc::new(egui::FontData::from_owned(bytes)));
        for family in [FontFamily::Proportional, FontFamily::Monospace] {
            fonts.families.entry(family).or_default().push(name.clone());
        }
    }
    ctx.set_fonts(fonts);
}
