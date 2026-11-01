//! Keyboard-possible mode: every chord sticks to one modifier, the way a real keyboard has to be played.
//!
//! A port of `src/autopiano/arrange/possible.py` (and the `enforce_key_gaps` it ends with); see
//! there for the reasoning. Each chord keeps the melody's modifier, or else whichever keeps the
//! most of the chord, and every other note is played an octave or two away, replaced by a nearby
//! copy of a note already sounding, or left out.

use std::collections::HashMap;

use crate::layout::Layout;
use crate::model::{Modifier, Note, Role};
use crate::timeline::chords_in_order;

const OCTAVE_REACH: i32 = 36;
const COPY_REACH: i32 = 12;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct PossibleReport {
    pub chords: usize,  // chords that mixed modifiers
    pub moved: usize,   // notes played an octave or two away
    pub doubled: usize, // notes replaced by a copy of another note of the chord
    pub dropped: usize, // notes left out
}

fn weight(role: Role) -> f64 {
    match role {
        Role::Melody => 100.0,
        Role::Bass => 2.0,
        Role::Harmony => 1.0,
    }
}

pub fn make_possible(notes: &[Note], layout: &Layout) -> (Vec<Note>, PossibleReport) {
    let mut report = PossibleReport::default();
    let mut out: Vec<Note> = Vec::new();
    let mut sounding: Vec<Note> = Vec::new(); // notes of earlier chords still held
    for chord in chords_in_order(notes) {
        let t = chord.iter().map(|n| n.start).fold(f64::INFINITY, f64::min);
        sounding.retain(|n| n.end() > t);
        let first = chord[0].modifier;
        let kept: Vec<Note> = if chord.iter().all(|n| n.modifier == first) {
            chord.iter().map(|n| (*n).clone()).collect()
        } else {
            report.chords += 1;
            one_modifier(&chord, &sounding, layout, &mut report)
        };
        out.extend(kept.iter().cloned());
        sounding.extend(kept);
    }
    let before = out.len();
    let spaced = enforce_key_gaps(out, 0.02, 0.01); // a moved note may now share a key with a note held from before
    report.dropped += before - spaced.len();
    (spaced, report)
}

fn one_modifier(chord: &[&Note], sounding: &[Note], layout: &Layout, report: &mut PossibleReport) -> Vec<Note> {
    let mut totals: Vec<(Modifier, f64)> = Vec::new(); // in order of first appearance, like a Python dict
    for n in chord {
        match totals.iter_mut().find(|(m, _)| *m == n.modifier) {
            Some((_, total)) => *total += weight(n.role),
            None => totals.push((n.modifier, weight(n.role))),
        }
    }
    let with_bass = |m: Modifier| chord.iter().any(|n| n.role == Role::Bass && n.modifier == m);
    // the most weight; on a tie, the bass's, then plain keys
    let mut target = totals[0].0;
    let mut best = (totals[0].1, with_bass(target), -(target as i32));
    for &(m, total) in &totals[1..] {
        let candidate = (total, with_bass(m), -(m as i32));
        if candidate.partial_cmp(&best) == Some(std::cmp::Ordering::Greater) {
            target = m;
            best = candidate;
        }
    }

    let mut kept: Vec<Note> = chord.iter().filter(|n| n.modifier == target).map(|n| (*n).clone()).collect();
    // the chord's own tune, or else the one still held from before
    let mut melody: Vec<i32> = kept.iter().filter(|n| n.role == Role::Melody).map(|n| n.pitch).collect();
    if melody.is_empty() {
        melody = sounding.iter().filter(|n| n.role == Role::Melody).map(|n| n.pitch).collect();
    }
    let ceiling = melody.iter().max().copied();
    let bottom = chord.iter().map(|n| n.pitch).min().unwrap();
    let held_keys: Vec<char> = sounding.iter().map(|n| n.key).collect();
    let mut misfits: Vec<&Note> = chord.iter().copied().filter(|n| n.modifier != target).collect();
    misfits.sort_by(|a, b| weight(b.role).total_cmp(&weight(a.role)).then(a.pitch.cmp(&b.pitch)));

    for n in misfits {
        let lowest = kept.iter().map(|k| k.pitch).min().unwrap();
        let in_bass = n.pitch == bottom; // it was the chord's lowest note, so its stand-in may go below the rest
        let pool: Vec<i32> = kept.iter().chain(sounding).map(|k| k.pitch.rem_euclid(12)).collect();
        let mut best: Option<((i32, bool, bool, i32, i32), i32, char)> = None;
        for (&pitch, &(key, modifier)) in &layout.keys {
            if modifier != target || kept.iter().any(|k| k.pitch == pitch || k.key == key) {
                continue;
            }
            if let Some(ceiling) = ceiling {
                if n.pitch < ceiling && ceiling <= pitch {
                    continue; // the tune stays on top
                }
            }
            if !in_bass && pitch < lowest {
                continue; // and the bass at the bottom
            }
            let distance = (pitch - n.pitch).abs();
            let tier = if pitch.rem_euclid(12) == n.pitch.rem_euclid(12) && distance <= OCTAVE_REACH {
                0
            } else if pool.contains(&pitch.rem_euclid(12)) && distance <= COPY_REACH {
                1
            } else {
                continue;
            };
            // a key that's still held would have to be let go early
            let score = (tier, in_bass && pitch > lowest, held_keys.contains(&key), distance, pitch);
            if best.is_none_or(|(b, _, _)| score < b) {
                best = Some((score, pitch, key));
            }
        }
        match best {
            None => report.dropped += 1,
            Some((score, pitch, key)) => {
                let mut role = n.role;
                if role == Role::Bass && pitch > lowest {
                    role = Role::Harmony;
                }
                kept.push(Note { pitch, key, modifier: target, role, ..n.clone() });
                if score.0 == 0 {
                    report.moved += 1;
                } else {
                    report.doubled += 1;
                }
            }
        }
    }
    kept
}

/// A key has to come up before it can go down again: notes sharing a physical key are spaced
/// so each is released `min_gap` before the next press, and when two presses are too close
/// for that, the less important note is dropped. Returns the notes sorted by (start, pitch).
pub fn enforce_key_gaps(notes: Vec<Note>, min_gap: f64, min_hold: f64) -> Vec<Note> {
    let mut order: Vec<char> = Vec::new();
    let mut by_key: HashMap<char, Vec<Note>> = HashMap::new();
    for n in notes {
        by_key
            .entry(n.key)
            .or_insert_with(|| {
                order.push(n.key);
                Vec::new()
            })
            .push(n);
    }
    let mut kept: Vec<Note> = Vec::new();
    for key in order {
        let mut same_key = by_key.remove(&key).unwrap();
        same_key.sort_by(|a, b| a.start.total_cmp(&b.start).then(b.role.cmp(&a.role)));
        let mut lane: Vec<Note> = Vec::new();
        for n in same_key {
            if let Some(prev) = lane.last_mut() {
                if n.start - prev.start < min_gap + min_hold {
                    if n.role > prev.role {
                        *prev = n;
                    }
                    continue;
                }
                if prev.end() > n.start - min_gap {
                    prev.duration = n.start - min_gap - prev.start;
                }
            }
            lane.push(n);
        }
        kept.extend(lane);
    }
    kept.sort_by(|a, b| a.start.total_cmp(&b.start).then(a.pitch.cmp(&b.pitch)));
    kept
}
