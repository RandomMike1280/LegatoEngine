"""Sends key events to the app in front (Roblox) through Quartz.

Every event carries explicit modifier flags, so a Shift the user happens to hold
can't turn a white key into a black one, and each event is tagged so the hotkey
listener can tell our own presses from the user's.
"""

from __future__ import annotations

import threading

import Quartz

from .timeline import MODIFIER_NAMES

# macOS virtual key codes (US ANSI positions).
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31,
    "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "space": 49, "shift": 56, "ctrl": 59,
}  # fmt: skip

_MODIFIER_BITS = {
    "shift": Quartz.kCGEventFlagMaskShift | 0x2,  # 0x2: left Shift, as a real keyboard sends
    "ctrl": Quartz.kCGEventFlagMaskControl | 0x1,  # 0x1: left Control
}
_ALL_MODIFIER_MASKS = (
    Quartz.kCGEventFlagMaskShift
    | Quartz.kCGEventFlagMaskControl
    | Quartz.kCGEventFlagMaskAlternate
    | Quartz.kCGEventFlagMaskCommand
    | Quartz.kCGEventFlagMaskAlphaShift
    | 0xFF  # device-specific left/right bits
) & ~Quartz.kCGEventFlagMaskNonCoalesced

EVENT_TAG = 0x41504E4F  # "APNO" in kCGEventSourceUserData marks events we posted


class MacKeyboard:
    def __init__(self) -> None:
        self._source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
        # By default macOS ignores the real keyboard for 0.25 s after each posted event,
        # which would swallow the user's stop hotkey during playback.
        Quartz.CGEventSourceSetLocalEventsSuppressionInterval(self._source, 0.0)
        probe = Quartz.CGEventCreateKeyboardEvent(self._source, KEYCODES["t"], True)
        self._base_flags = Quartz.CGEventGetFlags(probe) & ~_ALL_MODIFIER_MASKS
        self._down: set[str] = set()
        self._lock = threading.RLock()

    def send(self, key: str, down: bool) -> None:
        with self._lock:
            if (key in self._down) == down:
                return
            (self._down.add if down else self._down.discard)(key)
            flags = self._base_flags
            for modifier, bits in _MODIFIER_BITS.items():
                if modifier in self._down:
                    flags |= bits
            event = Quartz.CGEventCreateKeyboardEvent(self._source, KEYCODES[key], down)
            Quartz.CGEventSetFlags(event, flags)
            Quartz.CGEventSetIntegerValueField(event, Quartz.kCGEventSourceUserData, EVENT_TAG)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)

    def held_modifiers(self) -> set[str]:
        with self._lock:
            return self._down & MODIFIER_NAMES

    def release_all(self) -> None:
        with self._lock:
            held = set(self._down)
            for key in sorted(held - MODIFIER_NAMES) + sorted(held & MODIFIER_NAMES):
                self.send(key, False)
