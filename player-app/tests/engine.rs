//! The playback engine, with a keyboard that records what it's sent and when.
//! Mirrors the converter's tests/test_engine.py.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use legatoplayer::engine::{Player, State};
use legatoplayer::keys::{Backend, Keyboard};
use legatoplayer::timeline::{Action, Key};

#[derive(Clone, Default)]
struct Recorder {
    events: Arc<Mutex<Vec<(Instant, Key, bool)>>>,
    held: Arc<Mutex<BTreeSet<Key>>>,
}

impl Backend for Recorder {
    fn post(&mut self, key: Key, down: bool, held: &BTreeSet<Key>) {
        self.events.lock().unwrap().push((Instant::now(), key, down));
        *self.held.lock().unwrap() = held.clone();
    }
}

impl Recorder {
    fn keyboard(&self) -> Keyboard {
        Keyboard::with_backend(Box::new(self.clone()))
    }

    fn keys(&self) -> Vec<(Key, bool)> {
        self.events.lock().unwrap().iter().map(|&(_, k, d)| (k, d)).collect()
    }

    /// Seconds from `origin` to each event.
    fn times(&self, origin: Instant) -> Vec<f64> {
        self.events.lock().unwrap().iter().map(|(t, _, _)| t.duration_since(origin).as_secs_f64()).collect()
    }

    fn held(&self) -> BTreeSet<Key> {
        self.held.lock().unwrap().clone()
    }
}

fn act(time: f64, down: bool, key: Key) -> Action {
    Action { time, down, key }
}

const T: Key = Key::Char('t');

fn sleep(seconds: f64) {
    std::thread::sleep(Duration::from_secs_f64(seconds));
}

#[test]
fn events_land_on_time() {
    let times = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25];
    let actions: Vec<Action> = times.iter().enumerate().map(|(i, &t)| act(t, i % 2 == 0, T)).collect();
    let recorder = Recorder::default();
    let player = Player::new();
    player.play(Arc::new(actions), 1.0, 0.0, 0.0, recorder.keyboard());
    player.wait();
    let first = recorder.events.lock().unwrap()[0].0;
    let got = recorder.times(first);
    assert_eq!(got.len(), 6);
    for (want, got) in times.iter().zip(&got) {
        assert!((got - want).abs() < 0.002, "{want} vs {got}");
    }
}

#[test]
fn timing_is_accurate_over_many_events() {
    // 400 events 7 ms apart, like a fast run; each should land within a millisecond
    let actions: Vec<Action> =
        (0..400).map(|i| act(i as f64 * 0.007, i % 2 == 0, Key::Char(if i % 4 < 2 { 'a' } else { 's' }))).collect();
    let recorder = Recorder::default();
    let player = Player::new();
    player.play(Arc::new(actions.clone()), 1.0, 0.0, 0.0, recorder.keyboard());
    player.wait();
    let first = recorder.events.lock().unwrap()[0].0;
    let got = recorder.times(first);
    let late: Vec<f64> = actions.iter().zip(&got).map(|(a, t)| (t - a.time).abs()).collect();
    let worst = late.iter().cloned().fold(0.0, f64::max);
    let mean = late.iter().sum::<f64>() / late.len() as f64;
    println!("worst {:.3} ms, mean {:.3} ms", worst * 1000.0, mean * 1000.0);
    assert!(worst < 0.002, "worst {worst}");
}

#[test]
fn stop_lets_go_of_every_key() {
    let actions = vec![act(0.0, true, Key::Shift), act(0.001, true, T), act(5.0, false, T), act(5.0, false, Key::Shift)];
    let recorder = Recorder::default();
    let player = Player::new();
    player.play(Arc::new(actions), 1.0, 0.0, 0.0, recorder.keyboard());
    sleep(0.1);
    assert_eq!(recorder.held(), BTreeSet::from([Key::Shift, T]));
    player.stop();
    assert!(recorder.held().is_empty());
    assert_eq!(player.state(), State::Stopped);
    // piano keys first, then Shift
    assert_eq!(&recorder.keys()[2..], [(T, false), (Key::Shift, false)]);
}

#[test]
fn pause_releases_keys_and_resume_continues() {
    let (a, b) = (Key::Char('a'), Key::Char('b'));
    let actions = vec![act(0.0, true, a), act(0.3, false, a), act(0.4, true, b), act(0.5, false, b)];
    let recorder = Recorder::default();
    let player = Player::new();
    let started = Instant::now();
    player.play(Arc::new(actions), 1.0, 0.0, 0.0, recorder.keyboard());
    sleep(0.15);
    player.pause();
    sleep(0.1);
    assert_eq!(player.state(), State::Paused);
    assert!(recorder.held().is_empty()); // "a" was let go on pause
    sleep(0.2);
    player.resume();
    player.wait();
    assert_eq!(recorder.keys(), [(a, true), (a, false), (b, true), (b, false)]);
    let b_down = recorder.times(started)[2];
    assert!(0.65 < b_down && b_down < 0.75, "{b_down}"); // 0.4 s of song plus about 0.3 s paused
}

#[test]
fn pause_inside_a_shift_group_presses_shift_again_on_resume() {
    let two = Key::Char('2');
    let actions = vec![act(0.0, true, Key::Shift), act(0.2, true, two), act(0.3, false, two), act(0.3, false, Key::Shift)];
    let recorder = Recorder::default();
    let player = Player::new();
    player.play(Arc::new(actions), 1.0, 0.0, 0.0, recorder.keyboard());
    sleep(0.1);
    player.pause();
    sleep(0.05);
    assert!(recorder.held().is_empty());
    player.resume();
    player.wait();
    let keys = recorder.keys();
    let press = keys.iter().position(|&k| k == (two, true)).unwrap();
    assert_eq!(keys[press - 1], (Key::Shift, true)); // so "2" still plays the black key
}

#[test]
fn starting_inside_a_shift_group_presses_shift_first() {
    let two = Key::Char('2');
    let actions = vec![act(0.1, true, Key::Shift), act(0.2, true, two), act(0.3, false, Key::Shift), act(0.4, false, two)];
    let recorder = Recorder::default();
    let player = Player::new();
    player.play(Arc::new(actions), 1.0, 0.15, 0.0, recorder.keyboard());
    player.wait();
    assert_eq!(recorder.keys(), [(Key::Shift, true), (two, true), (Key::Shift, false), (two, false)]);
}

#[test]
fn countdown_then_play() {
    let recorder = Recorder::default();
    let player = Player::new();
    let states = Arc::new(Mutex::new(Vec::new()));
    let (seen, watched) = (states.clone(), player.clone());
    player.set_on_change(move || {
        let state = watched.state();
        let mut seen = seen.lock().unwrap();
        if seen.last() != Some(&state) {
            seen.push(state);
        }
    });
    let started = Instant::now();
    player.play(Arc::new(vec![act(0.0, true, T), act(0.05, false, T)]), 1.0, 0.0, 0.2, recorder.keyboard());
    player.wait();
    assert!(recorder.times(started)[0] >= 0.19);
    assert_eq!(*states.lock().unwrap(), [State::Countdown, State::Playing, State::Stopped]);
}

#[test]
fn toggle_during_countdown_cancels() {
    let recorder = Recorder::default();
    let player = Player::new();
    player.play(Arc::new(vec![act(0.0, true, T), act(0.05, false, T)]), 1.0, 0.0, 5.0, recorder.keyboard());
    sleep(0.05);
    let asked = Instant::now();
    player.toggle_pause();
    player.wait();
    assert!(asked.elapsed() < Duration::from_millis(200));
    assert!(recorder.keys().is_empty());
    assert_eq!(player.state(), State::Stopped);
}

#[test]
fn position_reaches_the_end_in_song_seconds() {
    let player = Player::new();
    player.play(Arc::new(vec![act(0.0, true, T), act(0.2, false, T)]), 2.0, 0.0, 0.0, Keyboard::dry_run());
    player.wait();
    assert_eq!(player.position(), 0.4);
    assert_eq!(player.last_run(), (1, true));
}

#[test]
fn speed_and_start_together() {
    // at half speed, the song's 1.0 s is 2.0 s of real time; starting from song second 0.5 skips the first press
    let (a, b) = (Key::Char('a'), Key::Char('b'));
    let actions = vec![act(0.0, true, a), act(0.2, false, a), act(1.2, true, b), act(1.4, false, b)];
    let recorder = Recorder::default();
    let player = Player::new();
    let started = Instant::now();
    player.play(Arc::new(actions), 0.5, 0.5, 0.0, recorder.keyboard());
    player.wait();
    assert_eq!(recorder.keys(), [(b, true), (b, false)]);
    let b_down = recorder.times(started)[0];
    assert!((b_down - 0.2).abs() < 0.01, "{b_down}"); // 1.2 s real minus the 1.0 s skipped
}

#[test]
fn position_moves_during_busy_passages() {
    // events 5 ms apart for 0.3 s: the playhead still moves every 30 ms or so
    let actions: Vec<Action> = (0..60).map(|i| act(i as f64 * 0.005, i % 2 == 0, T)).collect();
    let player = Player::new();
    let positions = Arc::new(Mutex::new(Vec::new()));
    let (seen, watched) = (positions.clone(), player.clone());
    player.set_on_change(move || seen.lock().unwrap().push(watched.position()));
    player.play(Arc::new(actions), 1.0, 0.0, 0.0, Keyboard::dry_run());
    player.wait();
    let mut distinct = positions.lock().unwrap().clone();
    distinct.dedup();
    assert!(distinct.len() >= 6, "{distinct:?}");
}
