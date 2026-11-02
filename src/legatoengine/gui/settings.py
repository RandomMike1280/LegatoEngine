"""Remembers choices between launches (stored in LegatoEngine's macOS preferences)."""

from __future__ import annotations

from PySide6.QtCore import QSettings


def load(key: str, default):
    value = QSettings().value(key, default)
    if value is None:
        return default
    try:
        if isinstance(default, bool):
            return value if isinstance(value, bool) else str(value).lower() in ("true", "1")
        if isinstance(default, int):
            return int(value)
        if isinstance(default, float):
            return float(value)
        if isinstance(default, str):
            return str(value)
    except (TypeError, ValueError):
        return default
    return value


def save(key: str, value) -> None:
    QSettings().setValue(key, value)


def copy_old_settings(old: QSettings | None = None) -> None:
    """Brings over the choices remembered before the rename, when there are none yet."""
    settings = QSettings()
    if settings.allKeys():
        return
    old = old or QSettings("autopiano.local", "AutoPiano")  # AutoPiano's organization domain and name
    for key in old.allKeys():
        settings.setValue(key, old.value(key))
