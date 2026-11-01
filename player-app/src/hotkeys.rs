//! Global hotkeys that work while Roblox is in front, so playback can be started, paused
//! and stopped without switching back to the player.
//!
//! The system delivers them on the window's thread, but straight to the handler given
//! here rather than through the window's redraw, so they work even while the window is
//! hidden behind the game.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use global_hotkey::hotkey::{Code, HotKey, Modifiers};
use global_hotkey::{GlobalHotKeyEvent, GlobalHotKeyManager, HotKeyState};

/// The keys that can be hotkeys: none of them plays a note in any layout.
pub const HOTKEYS: [&str; 23] = [
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", "`", "-", "=", "[", "]", "\\", ";",
    "'", ",", ".", "/",
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Command {
    TogglePause,
    Stop,
}

fn code(name: &str) -> Option<Code> {
    Some(match name {
        "F1" => Code::F1,
        "F2" => Code::F2,
        "F3" => Code::F3,
        "F4" => Code::F4,
        "F5" => Code::F5,
        "F6" => Code::F6,
        "F7" => Code::F7,
        "F8" => Code::F8,
        "F9" => Code::F9,
        "F10" => Code::F10,
        "F11" => Code::F11,
        "F12" => Code::F12,
        "`" => Code::Backquote,
        "-" => Code::Minus,
        "=" => Code::Equal,
        "[" => Code::BracketLeft,
        "]" => Code::BracketRight,
        "\\" => Code::Backslash,
        ";" => Code::Semicolon,
        "'" => Code::Quote,
        "," => Code::Comma,
        "." => Code::Period,
        "/" => Code::Slash,
        _ => return None,
    })
}

// The player holds Shift or Ctrl for a few milliseconds at a time, and the system counts
// those as held; each hotkey is registered with them too, so it still works at that moment.
const WITH: [Modifiers; 4] = [
    Modifiers::empty(),
    Modifiers::SHIFT,
    Modifiers::CONTROL,
    Modifiers::SHIFT.union(Modifiers::CONTROL),
];

pub struct Hotkeys {
    manager: Option<GlobalHotKeyManager>,
    registered: Vec<HotKey>,
    commands: Arc<Mutex<HashMap<u32, Command>>>,
    pub problem: Option<String>, // why hotkeys aren't working, to show the user
}

impl Hotkeys {
    /// Call on the window's thread. `on_command` runs there too, once per key press.
    pub fn start(on_command: impl Fn(Command) + Send + Sync + 'static) -> Hotkeys {
        let commands: Arc<Mutex<HashMap<u32, Command>>> = Arc::default();
        let manager = match GlobalHotKeyManager::new() {
            Ok(manager) => manager,
            Err(e) => {
                return Hotkeys {
                    manager: None,
                    registered: Vec::new(),
                    commands,
                    problem: Some(format!("Hotkeys aren't available: {e}.")),
                };
            }
        };
        let lookup = commands.clone();
        GlobalHotKeyEvent::set_event_handler(Some(move |event: GlobalHotKeyEvent| {
            if event.state() != HotKeyState::Pressed {
                return;
            }
            let command = lookup.lock().unwrap().get(&event.id()).copied();
            if let Some(command) = command {
                on_command(command);
            }
        }));
        Hotkeys { manager: Some(manager), registered: Vec::new(), commands, problem: None }
    }

    /// No hotkeys at all.
    pub fn off() -> Hotkeys {
        Hotkeys { manager: None, registered: Vec::new(), commands: Arc::default(), problem: None }
    }

    pub fn active(&self) -> bool {
        self.manager.is_some() && self.problem.is_none()
    }

    /// Uses `toggle` for play/pause and `stop` for stop, in place of the keys used before.
    pub fn bind(&mut self, toggle: &str, stop: &str) {
        let Some(manager) = &self.manager else { return };
        let _ = manager.unregister_all(&self.registered);
        self.registered.clear();
        let mut commands = self.commands.lock().unwrap();
        commands.clear();
        self.problem = None;
        if toggle == stop {
            self.problem = Some("Play/pause and stop need different hotkeys.".into());
            return;
        }
        let mut failed = Vec::new();
        for (name, command) in [(toggle, Command::TogglePause), (stop, Command::Stop)] {
            let Some(code) = code(name) else { continue };
            for (i, mods) in WITH.into_iter().enumerate() {
                let hotkey = HotKey::new(Some(mods), code);
                if manager.register(hotkey).is_ok() {
                    commands.insert(hotkey.id(), command);
                    self.registered.push(hotkey);
                } else if i == 0 {
                    failed.push(name); // the key on its own is the one that matters
                    break;
                }
            }
        }
        if !failed.is_empty() {
            self.problem = Some(format!(
                "Couldn't use {} as a hotkey; another app may have it. Pick a different one.",
                failed.join(" or ")
            ));
        }
    }
}
