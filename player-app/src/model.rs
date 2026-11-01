//! The data a script holds, as the player sees it.

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Role {
    Harmony = 0,
    Bass = 1,
    Melody = 2,
}

impl Role {
    pub fn from_int(value: i64) -> Option<Role> {
        match value {
            0 => Some(Role::Harmony),
            1 => Some(Role::Bass),
            2 => Some(Role::Melody),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Modifier {
    None = 0,
    Shift = 1,
    Ctrl = 2,
}

impl Modifier {
    pub fn from_int(value: i64) -> Option<Modifier> {
        match value {
            0 => Some(Modifier::None),
            1 => Some(Modifier::Shift),
            2 => Some(Modifier::Ctrl),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Note {
    pub pitch: i32, // MIDI note number, 60 = middle C
    pub start: f64, // seconds
    pub duration: f64,
    pub velocity: i32,
    pub role: Role,
    pub chord: i64,
    pub key: char, // physical key, such as 't'
    pub modifier: Modifier,
}

impl Note {
    pub fn end(&self) -> f64 {
        self.start + self.duration
    }
}

#[derive(Clone, Debug, Default)]
pub struct Meta {
    pub title: String,
    pub source_name: String,
    pub source_kind: String,
    pub duration: f64,
    pub bpm: f64,
    pub key_name: String,
    pub transpose: i64,
    pub layout_id: String,
    pub preset: String,
    pub created: f64,
}

#[derive(Clone, Debug, Default)]
pub struct Script {
    pub meta: Meta,
    pub notes: Vec<Note>, // sorted by start
    pub beats: Vec<f64>,
}

impl Script {
    pub fn chord_count(&self) -> usize {
        let mut chords: Vec<i64> = self.notes.iter().map(|n| n.chord).collect();
        chords.sort_unstable();
        chords.dedup();
        chords.len()
    }
}

const MAJOR_NAMES: [&str; 12] = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const MINOR_NAMES: [&str; 12] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];

/// "Eb major" moved down 3 semitones is "C major".
pub fn transposed_key_name(name: &str, shift: i64) -> String {
    let (tonic, mode) = name.split_once(' ').unwrap_or((name, ""));
    let names = if mode == "major" { &MAJOR_NAMES } else { &MINOR_NAMES };
    match names.iter().position(|n| *n == tonic) {
        Some(i) => format!("{} {}", names[(i as i64 + shift).rem_euclid(12) as usize], mode),
        None => name.to_string(),
    }
}
