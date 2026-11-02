"""Bring the Roblox window to the front before playing."""

from __future__ import annotations

from AppKit import (
    NSApplicationActivateAllWindows,
    NSApplicationActivateIgnoringOtherApps,
    NSRunningApplication,
    NSWorkspace,
)

ROBLOX_BUNDLE_IDS = ("com.roblox.RobloxPlayer",)


def find_roblox():
    for bundle_id in ROBLOX_BUNDLE_IDS:
        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle_id)
        if apps:
            return apps[0]
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        name = (app.localizedName() or "").lower()
        if name.startswith("roblox") and "studio" not in name:
            return app
    return None


def focus_roblox() -> bool:
    """True if Roblox is running and was asked to come to the front."""
    app = find_roblox()
    if app is None:
        return False
    return bool(app.activateWithOptions_(NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps))
