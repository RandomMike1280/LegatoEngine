//! Windows: key events through SendInput, precise sleeps and Roblox's window.

use std::collections::BTreeSet;

use windows_sys::Win32::Media::{timeBeginPeriod, timeEndPeriod};
use windows_sys::Win32::System::Threading::{GetCurrentThread, SetThreadPriority, THREAD_PRIORITY_TIME_CRITICAL};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, MAPVK_VK_TO_VSC, MapVirtualKeyW, SendInput, VK_LCONTROL,
    VK_LSHIFT,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{FindWindowW, IsIconic, SW_RESTORE, SetForegroundWindow, ShowWindow};

use crate::keys::Backend;
use crate::timeline::Key;

const EVENT_TAG: usize = 0x41504E4F; // "APNO", marks the events we sent

pub struct WinKeys;

impl Backend for WinKeys {
    fn post(&mut self, key: Key, down: bool, _held: &BTreeSet<Key>) {
        // Virtual keys follow the user's keyboard layout, as typing would; the scan code goes
        // along for games that read raw input.
        let vk: u16 = match key {
            Key::Shift => VK_LSHIFT,
            Key::Ctrl => VK_LCONTROL,
            Key::Char(c) => c.to_ascii_uppercase() as u16, // 'A'..'Z' and '0'..'9' are their own codes
        };
        unsafe {
            let scan = MapVirtualKeyW(vk as u32, MAPVK_VK_TO_VSC) as u16;
            let input = INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: vk,
                        wScan: scan,
                        dwFlags: if down { 0 } else { KEYEVENTF_KEYUP },
                        time: 0,
                        dwExtraInfo: EVENT_TAG,
                    },
                },
            };
            SendInput(1, &input, std::mem::size_of::<INPUT>() as i32);
        }
    }
}

/// True if a Roblox window was found and asked to come to the front.
pub fn focus_roblox() -> bool {
    let title: Vec<u16> = "Roblox\0".encode_utf16().collect();
    unsafe {
        let window = FindWindowW(std::ptr::null(), title.as_ptr());
        if window.is_null() {
            return false;
        }
        if IsIconic(window) != 0 {
            ShowWindow(window, SW_RESTORE);
        }
        SetForegroundWindow(window) != 0
    }
}

/// Accurate sleeps: a 1 ms system timer while playing, a high thread priority, and a short
/// spin before each deadline.
pub struct Sleeper;

impl Sleeper {
    /// Call on the thread that will sleep.
    pub fn new() -> Sleeper {
        unsafe {
            timeBeginPeriod(1);
            SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);
        }
        Sleeper
    }

    pub fn sleep(&self, seconds: f64) {
        crate::engine::sleep_then_spin(seconds);
    }
}

impl Drop for Sleeper {
    fn drop(&mut self) {
        unsafe { timeEndPeriod(1) };
    }
}
