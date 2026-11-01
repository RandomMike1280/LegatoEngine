#!/bin/bash
# Builds AutoPiano Player for every platform from this Mac:
#   dist/AutoPiano-Player-mac.zip      one app for both Apple Silicon and Intel Macs
#   dist/AutoPiano-Player-windows.zip  a single exe for 64-bit Windows 10 and 11
#
# Needs rustup with the aarch64-apple-darwin, x86_64-apple-darwin and x86_64-pc-windows-gnu
# targets, and MinGW (brew install mingw-w64) for the Windows exe.
set -euo pipefail

cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
export MACOSX_DEPLOYMENT_TARGET=10.15
VERSION=$(grep -m1 '^version' Cargo.toml | cut -d'"' -f2)
DIST=dist
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

for target in aarch64-apple-darwin x86_64-apple-darwin x86_64-pc-windows-gnu; do
    echo "== building for $target"
    cargo build --release --locked --target "$target"
done

rm -rf "$DIST"
mkdir -p "$DIST"

# ---- Mac: one universal app
echo "== packaging the Mac app"
APP="$STAGE/mac/AutoPiano Player.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
lipo -create -output "$APP/Contents/MacOS/autopiano-player" \
    target/aarch64-apple-darwin/release/autopiano-player \
    target/x86_64-apple-darwin/release/autopiano-player
cp packaging/icon.icns "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>AutoPiano Player</string>
    <key>CFBundleDisplayName</key><string>AutoPiano Player</string>
    <key>CFBundleIdentifier</key><string>local.autopiano.Player</string>
    <key>CFBundleExecutable</key><string>autopiano-player</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSMinimumSystemVersion</key><string>10.15</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
    <key>NSHighResolutionCapable</key><true/>
    <!-- App Nap would slow the player's timing while Roblox is in front -->
    <key>NSAppSleepDisabled</key><true/>
</dict>
</plist>
PLIST
codesign --force --deep --sign - "$APP"
cp packaging/read-me-mac.txt "$STAGE/mac/Read me.txt"
(cd "$STAGE/mac" && ditto -c -k --norsrc --noextattr --noacl . "$OLDPWD/$DIST/AutoPiano-Player-mac.zip")

# ---- Windows: the exe and its read-me
echo "== packaging the Windows exe"
mkdir -p "$STAGE/windows"
cp target/x86_64-pc-windows-gnu/release/autopiano-player.exe "$STAGE/windows/AutoPiano Player.exe"
# Windows Notepad wants CRLF line ends
sed 's/$/\r/' packaging/read-me-windows.txt > "$STAGE/windows/Read me.txt"
(cd "$STAGE/windows" && zip -q -X -r "$OLDPWD/$DIST/AutoPiano-Player-windows.zip" .)

echo "== done"
lipo -archs "$APP/Contents/MacOS/autopiano-player"
ls -lh "$DIST"
