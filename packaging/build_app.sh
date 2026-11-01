#!/usr/bin/env bash
# Builds dist/AutoPiano.app and signs it ad hoc so macOS can remember its permissions.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync
uv run pyinstaller --noconfirm --clean packaging/AutoPiano.spec
codesign --force --deep --sign - dist/AutoPiano.app
codesign --verify --deep --strict dist/AutoPiano.app
du -sh dist/AutoPiano.app
echo "Built dist/AutoPiano.app"
