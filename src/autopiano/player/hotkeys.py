"""Global hotkeys that work while Roblox is in front.

Uses a Quartz event tap. With Accessibility permission the tap swallows the hotkey,
so the game never sees it; with only Input Monitoring it falls back to listening.
Callbacks run on a separate thread so the tap never holds up the keyboard.
"""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Callable

import Quartz

from .keys_macos import EVENT_TAG

HOTKEYS = {
    "F1": 122, "F2": 120, "F3": 99, "F4": 118, "F5": 96, "F6": 97, "F7": 98, "F8": 100,
    "F9": 101, "F10": 109, "F11": 103, "F12": 111,
    "`": 50, "-": 27, "=": 24, "[": 33, "]": 30, "\\": 42, ";": 41, "'": 39, ",": 43, ".": 47, "/": 44,
}  # fmt: skip

_TAP_DISABLED = (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput)


class HotkeyListener:
    def __init__(self, bindings: dict[str, Callable[[], None]]):
        self.set_bindings(bindings)
        self.swallows = False  # True when the tap can hide hotkeys from the game
        self.active = False
        self._tap = None
        self._loop = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()
        self._calls: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._worker: threading.Thread | None = None

    def set_bindings(self, bindings: dict[str, Callable[[], None]]) -> None:
        self._codes = {HOTKEYS[name]: callback for name, callback in bindings.items()}

    def start(self, timeout: float = 2.0) -> bool:
        if self._thread and self._thread.is_alive():
            return self.active
        if self._worker is None:
            self._calls = queue.Queue()  # each worker gets its own queue, so a restart can't lose calls
            self._worker = threading.Thread(target=self._work, args=(self._calls,), name="autopiano-hotkey-calls", daemon=True)
            self._worker.start()
        self._started.clear()
        self._thread = threading.Thread(target=self._run, name="autopiano-hotkeys", daemon=True)
        self._thread.start()
        self._started.wait(timeout)
        return self.active

    def stop(self) -> None:
        thread = self._thread
        # CFRunLoopStop does nothing if the loop hasn't started running yet, so keep asking.
        for _ in range(20):
            if thread is None or not thread.is_alive():
                break
            if self._loop is not None:
                Quartz.CFRunLoopStop(self._loop)
            thread.join(timeout=0.1)
        self._thread = None
        self.active = False
        if self._worker is not None:
            self._calls.put(None)
            self._worker = None

    def _run(self) -> None:
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
        for option in (Quartz.kCGEventTapOptionDefault, Quartz.kCGEventTapOptionListenOnly):
            self._tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap, option, mask, self._callback, None
            )
            if self._tap is not None:
                self.swallows = option == Quartz.kCGEventTapOptionDefault
                break
        if self._tap is None:
            self._started.set()
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        self.active = True
        self._started.set()
        Quartz.CFRunLoopRun()
        Quartz.CGEventTapEnable(self._tap, False)
        self._loop = None
        self.active = False

    def _callback(self, proxy, event_type, event, refcon):
        if event_type in _TAP_DISABLED:
            Quartz.CGEventTapEnable(self._tap, True)  # macOS turns slow taps off; turn it back on
            return event
        if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData) == EVENT_TAG:
            return event
        code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        callback = self._codes.get(code)
        if callback is None:
            return event
        is_repeat = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
        if event_type == Quartz.kCGEventKeyDown and not is_repeat:
            self._calls.put(callback)
        return None

    @staticmethod
    def _work(calls: queue.Queue) -> None:
        while (callback := calls.get()) is not None:
            try:
                callback()
            except Exception:
                traceback.print_exc()
