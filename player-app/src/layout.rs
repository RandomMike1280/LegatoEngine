//! Keyboard layouts: which computer key, plus which modifier, plays each piano pitch.
//! Built into the player from the converter's own layout files, so the two never disagree.

use std::collections::BTreeMap;
use std::sync::OnceLock;

use serde::Deserialize;

use crate::model::Modifier;

const SOURCES: [&str; 2] = [
    include_str!("../../src/autopiano/layouts/vp61.json"),
    include_str!("../../src/autopiano/layouts/vp88.json"),
];
const WHITE_PITCH_CLASSES: [i32; 7] = [0, 2, 4, 5, 7, 9, 11];

#[derive(Deserialize)]
struct Extra {
    first_pitch: i32,
    keys: String,
    modifier: String,
}

#[derive(Deserialize)]
struct Source {
    id: String,
    name: String,
    low: i32,
    white_keys: String,
    #[serde(default)]
    extra: Vec<Extra>,
}

#[derive(Debug)]
pub struct Layout {
    pub id: String,
    pub name: String,
    pub low: i32,
    pub high: i32,
    pub keys: BTreeMap<i32, (char, Modifier)>, // pitch -> (physical key, modifier), in pitch order
}

impl Layout {
    pub fn lookup(&self, pitch: i32) -> Option<(char, Modifier)> {
        self.keys.get(&pitch).copied()
    }
}

pub fn is_black(pitch: i32) -> bool {
    !WHITE_PITCH_CLASSES.contains(&pitch.rem_euclid(12))
}

fn build(source: &str) -> Layout {
    let data: Source = serde_json::from_str(source).expect("built-in layouts are valid");
    let mut keys = BTreeMap::new();
    let mut pitch = data.low;
    let mut last_white = ' ';
    let mut white = data.white_keys.chars().peekable();
    while white.peek().is_some() {
        if is_black(pitch) {
            keys.insert(pitch, (last_white, Modifier::Shift));
        } else {
            last_white = white.next().unwrap();
            keys.insert(pitch, (last_white, Modifier::None));
        }
        pitch += 1;
    }
    for run in &data.extra {
        let modifier = match run.modifier.as_str() {
            "shift" => Modifier::Shift,
            "ctrl" => Modifier::Ctrl,
            _ => Modifier::None,
        };
        for (offset, key) in run.keys.chars().enumerate() {
            keys.insert(run.first_pitch + offset as i32, (key, modifier));
        }
    }
    Layout {
        id: data.id,
        name: data.name,
        low: *keys.keys().next().unwrap(),
        high: *keys.keys().next_back().unwrap(),
        keys,
    }
}

fn all() -> &'static Vec<Layout> {
    static LAYOUTS: OnceLock<Vec<Layout>> = OnceLock::new();
    LAYOUTS.get_or_init(|| SOURCES.iter().map(|s| build(s)).collect())
}

/// The layout a script was made for; unknown ids fall back to the 61-key layout.
pub fn load_layout(id: &str) -> &'static Layout {
    let layouts = all();
    layouts.iter().find(|l| l.id == id).unwrap_or(&layouts[0])
}
