//! Plays a timeline in real time on its own thread, with sub-millisecond accuracy.
//!
//! Every way out of playback (finish, stop, pause, a panic) lets go of all keys first,
//! so nothing stays stuck down. A port of `src/legatoengine/player/engine.py`.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::keys::Keyboard;
use crate::timeline::{Action, expected_modifiers};

const SPIN: f64 = 0.002; // spin for the last 2 ms before each event when sleeps aren't precise
const REPORT_EVERY: f64 = 0.03; // seconds between position updates (and stop/pause checks)

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
    Stopped,
    Countdown,
    Playing,
    Paused,
}

pub fn sleep_then_spin(seconds: f64) {
    if seconds <= 0.0 {
        return;
    }
    let end = Instant::now() + Duration::from_secs_f64(seconds);
    if seconds > SPIN {
        std::thread::sleep(Duration::from_secs_f64(seconds - SPIN));
    }
    while Instant::now() < end {
        std::hint::spin_loop();
    }
}

#[cfg(target_os = "macos")]
use crate::mac::Sleeper;
#[cfg(windows)]
use crate::win::Sleeper;
#[cfg(not(any(target_os = "macos", windows)))]
struct Sleeper;
#[cfg(not(any(target_os = "macos", windows)))]
impl Sleeper {
    fn new() -> Sleeper {
        Sleeper
    }
    fn sleep(&self, seconds: f64) {
        sleep_then_spin(seconds)
    }
}

struct Shared {
    state: Mutex<State>,
    position: AtomicU64,  // song seconds, as f64 bits
    countdown: AtomicU64, // seconds left, as f64 bits
    stop: AtomicBool,
    pause: AtomicBool,
    wake: (Mutex<bool>, Condvar),
    presses: AtomicU64,          // piano keys pressed in the last run
    last_run_was_dry: AtomicBool, // so the window can report a test run
    on_change: Mutex<Option<Box<dyn Fn() + Send>>>,
}

/// Controls playback from any thread.
#[derive(Clone)]
pub struct Player {
    shared: Arc<Shared>,
    thread: Arc<Mutex<Option<JoinHandle<()>>>>,
}

impl Default for Player {
    fn default() -> Self {
        Player::new()
    }
}

impl Player {
    pub fn new() -> Player {
        Player {
            shared: Arc::new(Shared {
                state: Mutex::new(State::Stopped),
                position: AtomicU64::new(0f64.to_bits()),
                countdown: AtomicU64::new(0f64.to_bits()),
                stop: AtomicBool::new(false),
                pause: AtomicBool::new(false),
                wake: (Mutex::new(false), Condvar::new()),
                presses: AtomicU64::new(0),
                last_run_was_dry: AtomicBool::new(false),
                on_change: Mutex::new(None),
            }),
            thread: Arc::new(Mutex::new(None)),
        }
    }

    /// Called from the player thread whenever the state or position changes.
    pub fn set_on_change(&self, callback: impl Fn() + Send + 'static) {
        *self.shared.on_change.lock().unwrap() = Some(Box::new(callback));
    }

    pub fn state(&self) -> State {
        *self.shared.state.lock().unwrap()
    }

    pub fn position(&self) -> f64 {
        f64::from_bits(self.shared.position.load(Ordering::Relaxed))
    }

    pub fn countdown_left(&self) -> f64 {
        f64::from_bits(self.shared.countdown.load(Ordering::Relaxed))
    }

    /// Piano keys pressed in the last run, and whether that run was a dry run.
    pub fn last_run(&self) -> (u64, bool) {
        (self.shared.presses.load(Ordering::Relaxed), self.shared.last_run_was_dry.load(Ordering::Relaxed))
    }

    /// Starts from `start` song seconds after an optional countdown.
    pub fn play(&self, actions: Arc<Vec<Action>>, speed: f64, start: f64, countdown: f64, keyboard: Keyboard) {
        self.stop();
        let shared = self.shared.clone();
        shared.stop.store(false, Ordering::SeqCst);
        shared.pause.store(false, Ordering::SeqCst);
        *shared.wake.0.lock().unwrap() = false;
        shared.position.store(start.to_bits(), Ordering::Relaxed);
        shared.last_run_was_dry.store(keyboard.is_dry_run(), Ordering::Relaxed);
        shared.presses.store(0, Ordering::Relaxed);
        set_state(&shared, State::Countdown); // so a second Play right away doesn't start another run
        let handle = std::thread::Builder::new()
            .name("legatoplayer".into())
            .spawn(move || run(shared, actions, speed, start / speed, countdown, keyboard))
            .expect("start the player thread");
        *self.thread.lock().unwrap() = Some(handle);
    }

    pub fn pause(&self) {
        if self.state() == State::Playing {
            self.shared.pause.store(true, Ordering::SeqCst);
            self.wake();
        }
    }

    pub fn resume(&self) {
        if self.shared.pause.swap(false, Ordering::SeqCst) {
            self.wake();
        }
    }

    pub fn toggle_pause(&self) {
        match self.state() {
            State::Countdown => self.stop(),
            State::Paused => self.resume(),
            State::Playing if self.shared.pause.load(Ordering::SeqCst) => self.resume(),
            State::Playing => self.pause(),
            State::Stopped => {}
        }
    }

    pub fn stop(&self) {
        let handle = self.thread.lock().unwrap().take();
        if let Some(handle) = handle {
            self.shared.stop.store(true, Ordering::SeqCst);
            self.wake();
            if handle.thread().id() != std::thread::current().id() {
                let _ = handle.join();
            }
        }
    }

    /// Blocks until playback ends (for tests and the command line).
    pub fn wait(&self) {
        let handle = self.thread.lock().unwrap().take();
        if let Some(handle) = handle {
            let _ = handle.join();
        }
    }

    fn wake(&self) {
        let (lock, condvar) = &self.shared.wake;
        *lock.lock().unwrap() = true;
        condvar.notify_all();
    }
}

fn notify(shared: &Shared) {
    if let Some(callback) = shared.on_change.lock().unwrap().as_ref() {
        callback();
    }
}

fn set_state(shared: &Shared, state: State) {
    *shared.state.lock().unwrap() = state;
    notify(shared);
}

fn report(shared: &Shared, position: f64) {
    shared.position.store(position.to_bits(), Ordering::Relaxed);
    notify(shared);
}

/// Waits on the wake signal for up to `seconds`.
fn wait_for_wake(shared: &Shared, seconds: f64) {
    let (lock, condvar) = &shared.wake;
    let woken = lock.lock().unwrap();
    let (mut woken, _) = condvar.wait_timeout(woken, Duration::from_secs_f64(seconds.max(0.0))).unwrap();
    *woken = false;
}

/// Lets go of every key even if playback panics.
struct ReleaseOnExit<'a> {
    shared: &'a Shared,
    keyboard: Keyboard,
}

impl Drop for ReleaseOnExit<'_> {
    fn drop(&mut self) {
        self.keyboard.release_all();
        self.shared.presses.store(self.keyboard.presses as u64, Ordering::Relaxed);
        set_state(self.shared, State::Stopped);
    }
}

fn run(shared: Arc<Shared>, actions: Arc<Vec<Action>>, speed: f64, start: f64, countdown: f64, keyboard: Keyboard) {
    let sleeper = Sleeper::new();
    let mut guard = ReleaseOnExit { shared: &shared, keyboard };
    if countdown > 0.0 && !count_down(&shared, countdown) {
        return;
    }
    let mut i = actions.partition_point(|a| a.time < start); // bisect_left
    for modifier in expected_modifiers(&actions, i) {
        guard.keyboard.send(modifier, true);
    }
    set_state(&shared, State::Playing);
    let mut origin = Instant::now() - Duration::from_secs_f64(start);
    let mut reported = Instant::now();
    while i < actions.len() && !shared.stop.load(Ordering::SeqCst) {
        if shared.pause.load(Ordering::SeqCst) {
            match pause(&shared, &mut guard.keyboard, origin) {
                Some(resumed) => origin = resumed,
                None => break,
            }
            continue;
        }
        let action = actions[i];
        if !wait_until(&shared, &sleeper, origin, action.time, speed, &mut reported) {
            continue;
        }
        guard.keyboard.send(action.key, action.down);
        i += 1;
    }
    if i >= actions.len() {
        report(&shared, actions.last().map_or(0.0, |a| a.time * speed));
    }
}

/// Waits for `target` seconds after `origin`, reporting the position every `REPORT_EVERY`
/// (`reported` is when it last did); false if interrupted by stop or pause.
fn wait_until(shared: &Shared, sleeper: &Sleeper, origin: Instant, target: f64, speed: f64, reported: &mut Instant) -> bool {
    loop {
        if shared.stop.load(Ordering::SeqCst) || shared.pause.load(Ordering::SeqCst) {
            return false;
        }
        let now = origin.elapsed().as_secs_f64();
        if reported.elapsed().as_secs_f64() >= REPORT_EVERY {
            report(shared, now * speed); // also during busy passages, where events are closer than this
            *reported = Instant::now();
        }
        let remaining = target - now;
        if remaining <= 0.0 {
            return true;
        }
        sleeper.sleep(remaining.min(REPORT_EVERY));
    }
}

/// Lets go of everything until resumed; returns the new origin, or None when stopped.
fn pause(shared: &Shared, keyboard: &mut Keyboard, origin: Instant) -> Option<Instant> {
    let paused_at = origin.elapsed();
    let modifiers = keyboard.held_modifiers();
    keyboard.release_all();
    set_state(shared, State::Paused);
    while shared.pause.load(Ordering::SeqCst) && !shared.stop.load(Ordering::SeqCst) {
        wait_for_wake(shared, 0.25);
    }
    if shared.stop.load(Ordering::SeqCst) {
        return None;
    }
    for modifier in modifiers {
        keyboard.send(modifier, true);
    }
    set_state(shared, State::Playing);
    Some(Instant::now() - paused_at)
}

fn count_down(shared: &Shared, seconds: f64) -> bool {
    let end = Instant::now() + Duration::from_secs_f64(seconds);
    set_state(shared, State::Countdown);
    while !shared.stop.load(Ordering::SeqCst) {
        let remaining = end.saturating_duration_since(Instant::now()).as_secs_f64();
        if remaining <= 0.0 {
            return true;
        }
        shared.countdown.store(remaining.to_bits(), Ordering::Relaxed);
        notify(shared);
        wait_for_wake(shared, remaining.min(0.1));
    }
    false
}
