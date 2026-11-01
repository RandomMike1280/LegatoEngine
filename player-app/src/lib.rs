//! AutoPiano Player: plays finished `.apno` scripts on Roblox pianos, on macOS and Windows.
//!
//! Converting songs needs the full AutoPiano app (Apple Silicon only); this player only
//! reads the scripts it writes, so it runs anywhere.

pub mod apno;
pub mod app;
pub mod engine;
pub mod hotkeys;
pub mod keys;
pub mod layout;
pub mod library;
pub mod model;
pub mod possible;
pub mod timeline;

#[cfg(target_os = "macos")]
pub mod mac;
#[cfg(windows)]
pub mod win;
