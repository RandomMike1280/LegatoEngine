"""Keyboards the player can send key events to."""

from __future__ import annotations

import threading
import time
from typing import Protocol

from .timeline import MODIFIER_NAMES


class Keyboard(Protocol):
    def send(self, key: str, down: bool) -> None: ...
    def held_modifiers(self) -> set[str]: ...
    def release_all(self) -> None: ...


class DryRunKeyboard:
    """Records key events instead of sending them. Used for tests and the dry-run mode."""

    def __init__(self, echo: bool = False):
        self.events: list[tuple[float, str, bool]] = []  # (seconds since first event, key, down)
        self.echo = echo
        self._down: set[str] = set()
        self._t0: float | None = None
        self._lock = threading.RLock()

    def send(self, key: str, down: bool) -> None:
        with self._lock:
            if (key in self._down) == down:
                return
            (self._down.add if down else self._down.discard)(key)
            now = time.perf_counter()
            if self._t0 is None:
                self._t0 = now
            self.events.append((now - self._t0, key, down))
            if self.echo:
                print(f"{now - self._t0:9.3f}s  {'down' if down else 'up  '}  {key}", flush=True)

    def held(self) -> set[str]:
        with self._lock:
            return set(self._down)

    def held_modifiers(self) -> set[str]:
        return self.held() & MODIFIER_NAMES

    def release_all(self) -> None:
        held = self.held()
        for key in sorted(held - MODIFIER_NAMES) + sorted(held & MODIFIER_NAMES):
            self.send(key, False)


def system_keyboard() -> Keyboard:
    from .keys_macos import MacKeyboard

    return MacKeyboard()
