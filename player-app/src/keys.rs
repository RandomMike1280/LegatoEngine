//! Keyboards the player sends key events to: the real one on macOS or Windows, or a
//! dry run that only counts what it would have sent.

use std::collections::BTreeSet;

use crate::timeline::Key;

/// Posts single key events to the system. `held` is every key currently down,
/// including this one when it's a press.
pub trait Backend: Send {
    fn post(&mut self, key: Key, down: bool, held: &BTreeSet<Key>);
}

/// Keeps track of what's down, so nothing is pressed twice and everything can be let go.
pub struct Keyboard {
    backend: Option<Box<dyn Backend>>, // None: a dry run
    down: BTreeSet<Key>,
    pub presses: usize,
}

impl Keyboard {
    pub fn dry_run() -> Keyboard {
        Keyboard { backend: None, down: BTreeSet::new(), presses: 0 }
    }

    pub fn system() -> Keyboard {
        Keyboard::with_backend(system_backend())
    }

    pub fn with_backend(backend: Box<dyn Backend>) -> Keyboard {
        Keyboard { backend: Some(backend), down: BTreeSet::new(), presses: 0 }
    }

    pub fn is_dry_run(&self) -> bool {
        self.backend.is_none()
    }

    pub fn send(&mut self, key: Key, down: bool) {
        if self.down.contains(&key) == down {
            return;
        }
        if down {
            self.down.insert(key);
            if !key.is_modifier() {
                self.presses += 1;
            }
        } else {
            self.down.remove(&key);
        }
        if let Some(backend) = self.backend.as_mut() {
            backend.post(key, down, &self.down);
        }
    }

    pub fn held_modifiers(&self) -> Vec<Key> {
        self.down.iter().copied().filter(|k| k.is_modifier()).collect()
    }

    /// Lets go of every key: piano keys first, then Shift and Ctrl.
    pub fn release_all(&mut self) {
        let held: Vec<Key> = self.down.iter().copied().collect();
        for key in held.iter().filter(|k| !k.is_modifier()).chain(held.iter().filter(|k| k.is_modifier())) {
            self.send(*key, false);
        }
    }
}

#[cfg(target_os = "macos")]
fn system_backend() -> Box<dyn Backend> {
    Box::new(crate::mac::MacKeys::new())
}

#[cfg(windows)]
fn system_backend() -> Box<dyn Backend> {
    Box::new(crate::win::WinKeys)
}

#[cfg(not(any(target_os = "macos", windows)))]
fn system_backend() -> Box<dyn Backend> {
    struct Nothing;
    impl Backend for Nothing {
        fn post(&mut self, _: Key, _: bool, _: &BTreeSet<Key>) {}
    }
    Box::new(Nothing)
}
