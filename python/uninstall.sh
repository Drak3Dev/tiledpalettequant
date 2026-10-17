#!/usr/bin/env bash
# Tiled Palette Quantizer uninstaller for Linux and macOS.
#   curl -fsSL https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/uninstall.sh | bash
# Environment override: TPQ_HOME (install dir, if it was changed during install).
set -euo pipefail

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    DEFAULT_HOME="$HOME/Library/Application Support/tiledpalettequant"
else
    DEFAULT_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/tiledpalettequant"
fi
DEST="${TPQ_HOME:-$DEFAULT_HOME}"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

removed=0
remove() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        rm -rf "$1"
        say "Removed $1"
        removed=1
    fi
}

if [ -d "$DEST" ]; then
    # Never delete a directory that isn't ours, e.g. a mistyped TPQ_HOME.
    if [ -f "$DEST/app/run.py" ] || [ -x "$DEST/venv/bin/python" ]; then
        cd /
        remove "$DEST"
    else
        die "$DEST doesn't look like a Tiled Palette Quantizer install, leaving it alone"
    fi
fi

for name in tiledpalettequant tiledpalettequant-cli tiledpalettequant-uninstall; do
    remove "$BIN_DIR/$name"
done

if [ "$OS" = "Darwin" ]; then
    remove "$HOME/Applications/Tiled Palette Quantizer.app"
else
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    remove "$APPS/tiledpalettequant.desktop"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPS" >/dev/null 2>&1 || true
    fi
fi

if [ "$removed" = 1 ]; then
    say "Tiled Palette Quantizer has been uninstalled."
else
    say "Tiled Palette Quantizer is not installed, nothing to remove."
fi
