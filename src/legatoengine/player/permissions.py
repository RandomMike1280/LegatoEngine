"""The macOS permission LegatoEngine needs to press keys in other apps."""

from __future__ import annotations

import subprocess

import Quartz
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

ACCESSIBILITY_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"


def can_send_keys() -> bool:
    return bool(Quartz.CGPreflightPostEventAccess()) or bool(AXIsProcessTrusted())


def request_key_access() -> bool:
    """Shows the macOS prompt that adds this app to the Accessibility list."""
    if Quartz.CGRequestPostEventAccess():
        return True
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))


def open_accessibility_settings() -> None:
    subprocess.Popen(["open", ACCESSIBILITY_SETTINGS])
