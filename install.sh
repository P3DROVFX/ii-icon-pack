#!/usr/bin/env bash
# ii-icon-pack installer for any Linux desktop.
#
#   curl -fsSL https://raw.githubusercontent.com/P3DROVFX/ii-icon-pack/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/P3DROVFX/ii-icon-pack/main/install.sh | bash -s -- --shape squircle --set-theme
#   ./install.sh --shape cookie-9 --glyph-scale 0.9
#
# Keeps a checkout in $XDG_DATA_HOME/ii-icon-pack (git when available, the GitHub tarball
# otherwise) and renders the theme into $XDG_DATA_HOME/icons/ii-icon-pack. Any flag is
# passed to `scripts/iipack.py install`; run `python3 scripts/iipack.py shapes` for the shapes.
# Running it again updates the pack and keeps the shape you picked.
set -euo pipefail

REPO="P3DROVFX/ii-icon-pack"
BRANCH="main"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
SRC="${II_ICON_PACK_SRC:-$DATA_HOME/ii-icon-pack}"

command -v python3 >/dev/null || { echo "ii-icon-pack needs python3" >&2; exit 1; }

# Running from inside a checkout: use it as is.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/scripts/iipack.py" ] && [ -d "$HERE/ii-icon-pack" ]; then
    SRC="$HERE"
elif [ -d "$SRC/.git" ] && command -v git >/dev/null; then
    echo "Updating $SRC"
    git -C "$SRC" pull --ff-only origin "$BRANCH"
elif [ -f "$SRC/scripts/iipack.py" ]; then
    # A tarball checkout: refresh it from GitHub when it moved on.
    if python3 "$SRC/scripts/iipack.py" update --check 2>/dev/null | grep -q "Update available"; then
        python3 "$SRC/scripts/iipack.py" update --source-only
    fi
elif command -v git >/dev/null; then
    echo "Downloading ii-icon-pack into $SRC"
    mkdir -p "$(dirname "$SRC")"
    git clone --depth 1 --branch "$BRANCH" "https://github.com/$REPO.git" "$SRC"
else
    echo "Downloading ii-icon-pack into $SRC"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar -xz -C "$tmp"
    mkdir -p "$(dirname "$SRC")"
    rm -rf "$SRC"
    mv "$tmp"/ii-icon-pack-* "$SRC"
fi

exec python3 "$SRC/scripts/iipack.py" install "$@"
