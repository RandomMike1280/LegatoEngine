#!/usr/bin/env bash
# Builds dist/LegatoEngine.app and signs it ad hoc so macOS can remember its permissions.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync
uv run pyinstaller --noconfirm --clean packaging/LegatoEngine.spec
codesign --force --deep --sign - dist/LegatoEngine.app
codesign --verify --deep --strict dist/LegatoEngine.app
du -sh dist/LegatoEngine.app
echo "Built dist/LegatoEngine.app"
