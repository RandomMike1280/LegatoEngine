"""Plays a timeline in real time with sub-millisecond accuracy.

Ordinary sleeps on macOS overshoot by up to ~8 ms. The player thread therefore asks
the kernel for the real-time scheduling policy audio apps use; with it,
``mach_wait_until`` wakes within a few microseconds of the deadline. If that isn't
available it falls back to sleeping most of the way and spinning the rest.

Every way out of playback (finish, stop, pause, an exception) lets go of all keys
first, so nothing stays stuck down.
"""

from __future__ import annotations

import bisect
import ctypes
import threading
import time
from enum import Enum
from typing import Callable

from .keyboard import Keyboard
from .timeline import Action, expected_modifiers

SPIN = 0.010  # fallback only: spin for the last 10 ms before each event
REPORT_EVERY = 0.03  # seconds between position updates (and stop/pause checks)


class State(str, Enum):
    STOPPED = "stopped"
    COUNTDOWN = "countdown"
    PLAYING = "playing"
    PAUSED = "paused"


class _TimeConstraintPolicy(ctypes.Structure):
    _fields_ = [
        ("period", ctypes.c_uint32),
        ("computation", ctypes.c_uint32),
        ("constraint", ctypes.c_uint32),
        ("preemptible", ctypes.c_int),
    ]


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


class PreciseSleeper:
    """Accurate sleeps for the calling thread. Create it on the thread that will sleep."""

    def __init__(self) -> None:
        self.precise = False
        try:
            lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
            lib.mach_absolute_time.restype = ctypes.c_uint64
            lib.mach_wait_until.argtypes = [ctypes.c_uint64]
            lib.mach_thread_self.restype = ctypes.c_uint32
            timebase = _Timebase()
            lib.mach_timebase_info(ctypes.byref(timebase))
            self._ticks_per_second = 1e9 * timebase.denom / timebase.numer
            ms = self._ticks_per_second / 1000
            policy = _TimeConstraintPolicy(int(5 * ms), int(1 * ms), int(2 * ms), 1)
            THREAD_TIME_CONSTRAINT_POLICY, COUNT = 2, 4
            result = lib.thread_policy_set(lib.mach_thread_self(), THREAD_TIME_CONSTRAINT_POLICY, ctypes.byref(policy), COUNT)
            self._lib = lib
            self.precise = result == 0
        except (OSError, AttributeError):
            pass

    @staticmethod
    def hold_off_app_nap():
        """Stops macOS throttling us while Roblox is the app in front. Returns a token."""
        try:
            from Foundation import NSProcessInfo

            user_initiated, latency_critical = 0x00FFFFFF, 0xFF00000000
            return NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
                user_initiated | latency_critical, "Playing a piano script"
            )
        except Exception:
            return None

    @staticmethod
    def allow_app_nap(token) -> None:
        if token is not None:
            from Foundation import NSProcessInfo

            NSProcessInfo.processInfo().endActivity_(token)

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        if self.precise:
            self._lib.mach_wait_until(self._lib.mach_absolute_time() + int(seconds * self._ticks_per_second))
            return
        end = time.perf_counter() + seconds
        if seconds > SPIN:
            time.sleep(seconds - SPIN)
        while time.perf_counter() < end:
            time.sleep(0)


class Player:
    def __init__(
        self,
        keyboard: Keyboard,
        on_state: Callable[[State], None] | None = None,
        on_position: Callable[[float], None] | None = None,
        on_countdown: Callable[[float], None] | None = None,
    ):
        self.keyboard = keyboard
        self.on_state = on_state
        self.on_position = on_position
        self.on_countdown = on_countdown
        self.state = State.STOPPED
        self.position = 0.0  # song seconds
        self._actions: list[Action] = []
        self._times: list[float] = []
        self._speed = 1.0
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._stop_requested = False
        self._pause_requested = False

    # ---- control (any thread)

    def load(self, actions: list[Action], speed: float = 1.0) -> None:
        self.stop()
        self._actions = actions
        self._times = [a.time for a in actions]
        self._speed = speed
        self.position = 0.0

    @property
    def duration(self) -> float:
        """Song seconds covered by the loaded timeline."""
        return self._times[-1] * self._speed if self._times else 0.0

    def play(self, start: float = 0.0, countdown: float = 0.0) -> None:
        """Start from ``start`` song seconds after an optional countdown."""
        self.stop()
        self._stop_requested = self._pause_requested = False
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._run, args=(start / self._speed, countdown), name="legatoengine-player", daemon=True
        )
        self._thread.start()

    def pause(self) -> None:
        if self.state is State.PLAYING:
            self._pause_requested = True
            self._wake.set()

    def resume(self) -> None:
        if self._pause_requested:
            self._pause_requested = False
            self._wake.set()

    def toggle_pause(self) -> None:
        if self.state is State.COUNTDOWN:
            self.stop()
        elif self.state is State.PAUSED or self._pause_requested:
            self.resume()
        elif self.state is State.PLAYING:
            self.pause()

    def stop(self) -> None:
        thread = self._thread
        if thread and thread.is_alive():
            self._stop_requested = True
            self._wake.set()
            if thread is not threading.current_thread():
                thread.join(timeout=2)
        self._thread = None

    def wait(self, timeout: float | None = None) -> bool:
        """Block until playback ends. Returns False on timeout."""
        thread = self._thread
        if thread:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    # ---- player thread

    def _run(self, start: float, countdown: float) -> None:
        self._sleeper = PreciseSleeper()
        activity = self._sleeper.hold_off_app_nap()
        kb = self.keyboard
        try:
            if countdown > 0 and not self._countdown(countdown):
                return
            i = bisect.bisect_left(self._times, start)
            for modifier in sorted(expected_modifiers(self._actions, i)):
                kb.send(modifier, True)
            self._set_state(State.PLAYING)
            origin = time.perf_counter() - start
            n = len(self._actions)
            while i < n and not self._stop_requested:
                if self._pause_requested:
                    origin = self._pause(origin)
                    if origin is None:
                        break
                    continue
                action = self._actions[i]
                if not self._wait_until(origin + action.time, origin):
                    continue
                kb.send(action.key, action.down)
                i += 1
            if i >= n:
                self._report(self.duration)
        finally:
            kb.release_all()
            self._sleeper.allow_app_nap(activity)
            self._set_state(State.STOPPED)

    def _wait_until(self, target: float, origin: float) -> bool:
        """Wait for ``target``; False if interrupted by stop or pause."""
        while True:
            if self._stop_requested or self._pause_requested:
                return False
            remaining = target - time.perf_counter()
            if remaining <= 0:
                return True
            if remaining > REPORT_EVERY:
                self._sleeper.sleep(REPORT_EVERY)
                self._report((time.perf_counter() - origin) * self._speed)
            else:
                self._sleeper.sleep(remaining)

    def _pause(self, origin: float) -> float | None:
        paused_at = time.perf_counter() - origin
        modifiers = self.keyboard.held_modifiers()
        self.keyboard.release_all()
        self._set_state(State.PAUSED)
        while self._pause_requested and not self._stop_requested:
            self._wake.wait(0.25)
            self._wake.clear()
        if self._stop_requested:
            return None
        for modifier in sorted(modifiers):
            self.keyboard.send(modifier, True)
        self._set_state(State.PLAYING)
        return time.perf_counter() - paused_at

    def _countdown(self, seconds: float) -> bool:
        end = time.perf_counter() + seconds
        self._set_state(State.COUNTDOWN)
        while not self._stop_requested:
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return True
            self._call(self.on_countdown, remaining)
            if self._wake.wait(min(remaining, 0.1)):
                self._wake.clear()
        return False

    def _report(self, position: float) -> None:
        self.position = position
        self._call(self.on_position, position)

    def _set_state(self, state: State) -> None:
        self.state = state
        self._call(self.on_state, state)

    @staticmethod
    def _call(callback, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  # a broken UI callback must never stop the player mid-song
            import traceback

            traceback.print_exc()
