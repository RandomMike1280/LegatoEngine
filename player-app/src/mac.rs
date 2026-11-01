//! macOS: key events through Quartz, precise sleeps, the Accessibility check and Roblox's window.

use std::collections::BTreeSet;
use std::ffi::c_void;
use std::process::Command;

use crate::keys::Backend;
use crate::timeline::Key;

type CFTypeRef = *const c_void;

#[link(name = "CoreGraphics", kind = "framework")]
unsafe extern "C" {
    fn CGEventSourceCreate(state: i32) -> CFTypeRef;
    fn CGEventSourceSetLocalEventsSuppressionInterval(source: CFTypeRef, seconds: f64);
    fn CGEventCreateKeyboardEvent(source: CFTypeRef, keycode: u16, down: bool) -> CFTypeRef;
    fn CGEventGetFlags(event: CFTypeRef) -> u64;
    fn CGEventSetFlags(event: CFTypeRef, flags: u64);
    fn CGEventSetIntegerValueField(event: CFTypeRef, field: u32, value: i64);
    fn CGEventPost(tap: u32, event: CFTypeRef);
}

#[link(name = "CoreFoundation", kind = "framework")]
unsafe extern "C" {
    fn CFRelease(object: CFTypeRef);
    fn CFDictionaryCreate(
        allocator: CFTypeRef,
        keys: *const CFTypeRef,
        values: *const CFTypeRef,
        count: isize,
        key_callbacks: *const c_void,
        value_callbacks: *const c_void,
    ) -> CFTypeRef;
    static kCFBooleanTrue: CFTypeRef;
    static kCFTypeDictionaryKeyCallBacks: c_void;
    static kCFTypeDictionaryValueCallBacks: c_void;
}

#[link(name = "ApplicationServices", kind = "framework")]
unsafe extern "C" {
    fn AXIsProcessTrusted() -> bool;
    fn AXIsProcessTrustedWithOptions(options: CFTypeRef) -> bool;
    static kAXTrustedCheckOptionPrompt: CFTypeRef;
}

const HID_SYSTEM_STATE: i32 = 1;
const HID_EVENT_TAP: u32 = 0;
const SOURCE_USER_DATA: u32 = 42;
const EVENT_TAG: i64 = 0x41504E4F; // "APNO", the same tag the converter's player uses

const FLAG_SHIFT: u64 = 0x0002_0000 | 0x2; // 0x2: left Shift, as a real keyboard sends
const FLAG_CONTROL: u64 = 0x0004_0000 | 0x1; // 0x1: left Control
const ALL_MODIFIERS: u64 = (0x0001_0000 | 0x0002_0000 | 0x0004_0000 | 0x0008_0000 | 0x0010_0000 | 0xFF) & !0x100;

/// macOS virtual key codes (US ANSI positions).
fn keycode(key: Key) -> u16 {
    match key {
        Key::Shift => 56,
        Key::Ctrl => 59,
        Key::Char(c) => match c {
            'a' => 0, 's' => 1, 'd' => 2, 'f' => 3, 'h' => 4, 'g' => 5, 'z' => 6, 'x' => 7, 'c' => 8,
            'v' => 9, 'b' => 11, 'q' => 12, 'w' => 13, 'e' => 14, 'r' => 15, 'y' => 16, 't' => 17,
            '1' => 18, '2' => 19, '3' => 20, '4' => 21, '6' => 22, '5' => 23, '9' => 25, '7' => 26,
            '8' => 28, '0' => 29, 'o' => 31, 'u' => 32, 'i' => 34, 'p' => 35, 'l' => 37, 'j' => 38,
            'k' => 40, 'n' => 45, 'm' => 46,
            _ => 49, // space: harmless if a script ever holds a key this player doesn't know
        },
    }
}

pub struct MacKeys {
    source: CFTypeRef,
    base_flags: u64,
}

// The event source is only used from the player thread that owns this keyboard.
unsafe impl Send for MacKeys {}

impl MacKeys {
    pub fn new() -> MacKeys {
        unsafe {
            let source = CGEventSourceCreate(HID_SYSTEM_STATE);
            // By default macOS ignores the real keyboard for 0.25 s after each posted event,
            // which would swallow the user's stop hotkey during playback.
            CGEventSourceSetLocalEventsSuppressionInterval(source, 0.0);
            let probe = CGEventCreateKeyboardEvent(source, keycode(Key::Char('t')), true);
            let base_flags = CGEventGetFlags(probe) & !ALL_MODIFIERS;
            CFRelease(probe);
            MacKeys { source, base_flags }
        }
    }
}

impl Drop for MacKeys {
    fn drop(&mut self) {
        unsafe { CFRelease(self.source) }
    }
}

impl Backend for MacKeys {
    fn post(&mut self, key: Key, down: bool, held: &BTreeSet<Key>) {
        // Every event carries explicit modifier flags, so a Shift the user happens to hold
        // can't turn a white key into a black one.
        let mut flags = self.base_flags;
        if held.contains(&Key::Shift) {
            flags |= FLAG_SHIFT;
        }
        if held.contains(&Key::Ctrl) {
            flags |= FLAG_CONTROL;
        }
        unsafe {
            let event = CGEventCreateKeyboardEvent(self.source, keycode(key), down);
            CGEventSetFlags(event, flags);
            CGEventSetIntegerValueField(event, SOURCE_USER_DATA, EVENT_TAG);
            CGEventPost(HID_EVENT_TAP, event);
            CFRelease(event);
        }
    }
}

/// Whether macOS lets this app press keys in other apps.
pub fn can_send_keys() -> bool {
    unsafe { AXIsProcessTrusted() }
}

/// Asks macOS to show its "allow this app" prompt, which also adds the app to the Accessibility list.
pub fn ask_for_key_access() -> bool {
    unsafe {
        let keys = [kAXTrustedCheckOptionPrompt];
        let values = [kCFBooleanTrue];
        let options = CFDictionaryCreate(
            std::ptr::null(),
            keys.as_ptr(),
            values.as_ptr(),
            1,
            &kCFTypeDictionaryKeyCallBacks,
            &kCFTypeDictionaryValueCallBacks,
        );
        let trusted = AXIsProcessTrustedWithOptions(options);
        CFRelease(options);
        trusted
    }
}

pub fn open_accessibility_settings() {
    let _ = Command::new("open")
        .arg("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        .spawn();
}

/// True if Roblox is running and was asked to come to the front.
pub fn focus_roblox() -> bool {
    let running = Command::new("pgrep").args(["-x", "RobloxPlayer"]).output().is_ok_and(|o| o.status.success());
    if !running {
        return false;
    }
    Command::new("open").args(["-b", "com.roblox.RobloxPlayer"]).status().map(|s| s.success()).unwrap_or(false)
}

// ---- precise sleeps

#[repr(C)]
struct TimeConstraintPolicy {
    period: u32,
    computation: u32,
    constraint: u32,
    preemptible: i32,
}

#[repr(C)]
struct Timebase {
    numer: u32,
    denom: u32,
}

unsafe extern "C" {
    fn mach_absolute_time() -> u64;
    fn mach_wait_until(deadline: u64) -> i32;
    fn mach_thread_self() -> u32;
    fn mach_timebase_info(info: *mut Timebase) -> i32;
    fn thread_policy_set(thread: u32, flavor: u32, policy: *const TimeConstraintPolicy, count: u32) -> i32;
}

/// Accurate sleeps for the calling thread. Ordinary sleeps on macOS overshoot by up to ~8 ms,
/// so the player thread asks for the real-time scheduling audio apps use; with it,
/// `mach_wait_until` wakes within a few microseconds of the deadline.
pub struct Sleeper {
    ticks_per_second: f64,
    precise: bool,
}

impl Sleeper {
    /// Call on the thread that will sleep.
    pub fn new() -> Sleeper {
        unsafe {
            let mut timebase = Timebase { numer: 0, denom: 0 };
            mach_timebase_info(&mut timebase);
            let ticks_per_second = 1e9 * timebase.denom as f64 / timebase.numer as f64;
            let ms = ticks_per_second / 1000.0;
            let policy = TimeConstraintPolicy {
                period: (5.0 * ms) as u32,
                computation: ms as u32,
                constraint: (2.0 * ms) as u32,
                preemptible: 1,
            };
            const THREAD_TIME_CONSTRAINT_POLICY: u32 = 2;
            let precise = thread_policy_set(mach_thread_self(), THREAD_TIME_CONSTRAINT_POLICY, &policy, 4) == 0;
            Sleeper { ticks_per_second, precise }
        }
    }

    pub fn sleep(&self, seconds: f64) {
        if seconds <= 0.0 {
            return;
        }
        if self.precise {
            unsafe { mach_wait_until(mach_absolute_time() + (seconds * self.ticks_per_second) as u64) };
        } else {
            crate::engine::sleep_then_spin(seconds);
        }
    }
}
