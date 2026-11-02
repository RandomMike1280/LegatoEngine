#!/usr/bin/env bash
# Builds everything and gathers it in release/ (git ignores it):
#   LegatoEngine-mac.zip      LegatoEngine.app, for Apple Silicon Macs
#   LegatoPlayer-mac.zip      the player for Apple Silicon and Intel Macs
#   LegatoPlayer-windows.zip  the player for 64-bit Windows
#   LegatoEngine-source.zip   the source, for building it yourself (see README.md)
#   SHA256SUMS.txt
set -euo pipefail
cd "$(dirname "$0")/.."

packaging/build_app.sh
player-app/packaging/build.sh

rm -rf release
mkdir release
echo "== gathering release/"
ditto -c -k --norsrc --noextattr --noacl --keepParent dist/LegatoEngine.app release/LegatoEngine-mac.zip
cp player-app/dist/LegatoPlayer-mac.zip player-app/dist/LegatoPlayer-windows.zip release/

# The source as the apps were just built from it: every file git tracks or would add, including
# uncommitted changes. A scratch index keeps git's own staging area untouched.
INDEX=$(mktemp)
trap 'rm -f "$INDEX"' EXIT
cp "$(git rev-parse --git-path index)" "$INDEX"
GIT_INDEX_FILE="$INDEX" git add --all
TREE=$(GIT_INDEX_FILE="$INDEX" git write-tree)
git archive --format=zip --prefix=LegatoEngine/ -o release/LegatoEngine-source.zip "$TREE"

(cd release && shasum -a 256 *.zip > SHA256SUMS.txt)
ls -lh release
if [ "$TREE" = "$(git rev-parse 'HEAD^{tree}')" ]; then
    echo "Released commit $(git rev-parse --short HEAD) to release/"
else
    echo "Released commit $(git rev-parse --short HEAD) plus uncommitted changes to release/"
fi
