//! Turns a script's notes into the exact key presses the player sends.
//!
//! Holding Shift while pressing a white key would play the black key instead, so each
//! chord is pressed in groups: plain keys first, then Shift down, the black keys, Shift
//! up, then the same for Ctrl. Key releases are moved out of those modifier windows,
//! and a key is always released long enough before it is pressed again.
//!
//! This is a line-for-line port of `src/legatoengine/player/timeline.py`; the parity test
//! checks both give the same presses at the same times.

use std::collections::HashMap;
use std::fmt;

use crate::model::{Modifier, Note};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Key {
    Char(char), // a piano key such as 't'
    Shift,
    Ctrl,
}

impl Key {
    pub fn is_modifier(self) -> bool {
        !matches!(self, Key::Char(_))
    }

    fn for_modifier(modifier: Modifier) -> Option<Key> {
        match modifier {
            Modifier::None => None,
            Modifier::Shift => Some(Key::Shift),
            Modifier::Ctrl => Some(Key::Ctrl),
        }
    }
}

impl fmt::Display for Key {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Key::Char(c) => write!(f, "{c}"),
            Key::Shift => f.write_str("shift"),
            Key::Ctrl => f.write_str("ctrl"),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Action {
    pub time: f64, // seconds of real time from the start of the song (speed already applied)
    pub down: bool,
    pub key: Key,
}

#[derive(Clone, Debug)]
pub struct PlaySettings {
    pub speed: f64,
    pub tap: bool, // let go right away instead of holding each note for its length
    pub tap_time: f64,
    pub max_hold: f64,
    pub press_gap: f64,  // between key events inside one chord
    pub min_regap: f64, // a key stays up at least this long (about one frame) before a re-press
}

impl Default for PlaySettings {
    fn default() -> Self {
        PlaySettings { speed: 1.0, tap: false, tap_time: 0.03, max_hold: 8.0, press_gap: 0.001, min_regap: 0.017 }
    }
}

struct Hold {
    press: f64,
    release: f64,
    key: Key,
}

const GROUP_ORDER: [Modifier; 3] = [Modifier::None, Modifier::Shift, Modifier::Ctrl];

/// Notes grouped by chord number, in order of first appearance, then sorted by when they start.
pub fn chords_in_order(notes: &[Note]) -> Vec<Vec<&Note>> {
    let mut index: HashMap<i64, usize> = HashMap::new();
    let mut chords: Vec<Vec<&Note>> = Vec::new();
    for n in notes {
        let i = *index.entry(n.chord).or_insert_with(|| {
            chords.push(Vec::new());
            chords.len() - 1
        });
        chords[i].push(n);
    }
    chords.sort_by(|a, b| min_start(a).total_cmp(&min_start(b))); // stable, like Python's sorted
    chords
}

pub fn min_start(chord: &[&Note]) -> f64 {
    chord.iter().map(|n| n.start).fold(f64::INFINITY, f64::min)
}

pub fn build_timeline(notes: &[Note], s: &PlaySettings) -> Vec<Action> {
    let gap = s.press_gap;
    let mut presses: Vec<Action> = Vec::new();
    let mut windows: Vec<(f64, f64)> = Vec::new(); // when a modifier is held
    let mut holds: Vec<Hold> = Vec::new();
    let mut cursor = f64::NEG_INFINITY;
    for chord in chords_in_order(notes) {
        let mut t = (min_start(&chord) / s.speed).max(cursor);
        for modifier in GROUP_ORDER {
            let mut group: Vec<&Note> = chord.iter().copied().filter(|n| n.modifier == modifier).collect();
            if group.is_empty() {
                continue;
            }
            group.sort_by_key(|n| n.pitch);
            let mod_key = Key::for_modifier(modifier);
            let mut window_start = 0.0;
            if let Some(key) = mod_key {
                presses.push(Action { time: t, down: true, key });
                window_start = t;
                t += gap;
            }
            for n in group {
                presses.push(Action { time: t, down: true, key: Key::Char(n.key) });
                let hold = if s.tap { s.tap_time } else { (n.duration / s.speed).min(s.max_hold) };
                holds.push(Hold { press: t, release: t + hold.max(gap), key: Key::Char(n.key) });
                t += gap;
            }
            if let Some(key) = mod_key {
                presses.push(Action { time: t, down: false, key });
                windows.push((window_start, t));
                t += gap;
            }
        }
        cursor = t;
    }

    move_releases_out_of_windows(&mut holds, &windows, gap);
    release_before_repress(&mut holds, &windows, gap, s.min_regap);

    let mut actions = presses;
    actions.extend(holds.iter().map(|h| Action { time: h.release, down: false, key: h.key }));
    actions.sort_by(|a, b| a.time.total_cmp(&b.time)); // stable: presses keep their order at equal times
    actions
}

fn window_containing(windows: &[(f64, f64)], t: f64) -> Option<(f64, f64)> {
    let i = windows.partition_point(|w| w.0 <= t); // bisect_right on the window starts
    if i == 0 {
        return None;
    }
    let w = windows[i - 1];
    (w.0 <= t && t <= w.1).then_some(w)
}

fn move_releases_out_of_windows(holds: &mut [Hold], windows: &[(f64, f64)], gap: f64) {
    for hold in holds.iter_mut() {
        if let Some(w) = window_containing(windows, hold.release) {
            if hold.press < w.0 - gap / 2.0 {
                hold.release = w.0 - gap / 2.0; // let go just before the modifier goes down
            } else {
                hold.release = w.1 + gap / 2.0; // pressed inside this window: let go after it
            }
        }
    }
}

fn release_before_repress(holds: &mut [Hold], windows: &[(f64, f64)], gap: f64, min_regap: f64) {
    let mut by_key: HashMap<Key, Vec<usize>> = HashMap::new();
    for (i, hold) in holds.iter().enumerate() {
        by_key.entry(hold.key).or_default().push(i);
    }
    for mut lane in by_key.into_values() {
        lane.sort_by(|&a, &b| holds[a].press.total_cmp(&holds[b].press));
        for pair in lane.windows(2) {
            let (current, following) = (pair[0], pair[1]);
            let latest = holds[following].press - min_regap;
            if holds[current].release <= latest {
                continue;
            }
            let press = holds[current].press;
            let release = if latest > press {
                match window_containing(windows, latest) {
                    Some(w) if w.0 - gap / 2.0 > press => w.0 - gap / 2.0,
                    _ => latest,
                }
            } else {
                press + (holds[following].press - press) / 2.0 // too close: best effort
            };
            holds[current].release = release;
        }
    }
}

/// Modifiers that should be held just before `actions[index]` is sent.
pub fn expected_modifiers(actions: &[Action], index: usize) -> Vec<Key> {
    let mut held: Vec<Key> = Vec::new();
    for a in &actions[..index.min(actions.len())] {
        if a.key.is_modifier() {
            held.retain(|k| *k != a.key);
            if a.down {
                held.push(a.key);
            }
        }
    }
    held.sort();
    held
}
