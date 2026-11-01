//! What the parity check compares: a script as the player reads it, the key presses it
//! makes of it, and its keyboard-possible version, in the same shape `parity.py` writes.

use autopiano_player::layout::load_layout;
use autopiano_player::model::{Note, Script};
use autopiano_player::possible::make_possible;
use autopiano_player::timeline::{Action, PlaySettings, build_timeline};
use serde_json::{Value, json};

pub const SETTINGS: [(f64, bool); 5] = [(1.0, false), (0.75, false), (1.5, false), (1.0, true), (1.25, true)];

fn note_rows(notes: &[Note]) -> Value {
    notes
        .iter()
        .map(|n| {
            json!([n.pitch, n.start, n.duration, n.velocity, n.role as i32, n.chord, n.key.to_string(), n.modifier as i32])
        })
        .collect()
}

fn action_rows(actions: &[Action]) -> Value {
    actions.iter().map(|a| json!([a.time, a.down, a.key.to_string()])).collect()
}

pub fn describe(script: &Script) -> Value {
    let layout = load_layout(&script.meta.layout_id);
    let (possible, report) = make_possible(&script.notes, layout);
    let timelines: Vec<Value> = SETTINGS
        .iter()
        .map(|&(speed, tap)| {
            let actions = build_timeline(&script.notes, &PlaySettings { speed, tap, ..Default::default() });
            json!({"speed": speed, "tap": tap, "actions": action_rows(&actions)})
        })
        .collect();
    let m = &script.meta;
    json!({
        "meta": {"title": m.title, "duration": m.duration, "key_name": m.key_name, "transpose": m.transpose,
                 "layout_id": m.layout_id, "bpm": m.bpm, "source_kind": m.source_kind},
        "notes": note_rows(&script.notes),
        "beats": script.beats,
        "timelines": timelines,
        "possible": {
            "notes": note_rows(&possible),
            "report": [report.chords, report.moved, report.doubled, report.dropped],
            "actions": action_rows(&build_timeline(&possible, &PlaySettings::default())),
        },
    })
}
