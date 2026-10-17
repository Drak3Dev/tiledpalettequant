#!/usr/bin/env bash
# Tiled Palette Quantizer installer for Linux and macOS.
#   curl -fsSL https://raw.githubusercontent.com/Drak3Dev/tiledpalettequant/main/python/install.sh | bash
# Environment overrides: TPQ_HOME (install dir), TPQ_BRANCH (git branch), TPQ_SRC_DIR (local source).
set -euo pipefail

REPO="Drak3Dev/tiledpalettequant"
BRANCH="${TPQ_BRANCH:-main}"
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    DEFAULT_HOME="$HOME/Library/Application Support/tiledpalettequant"
else
    DEFAULT_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/tiledpalettequant"
fi
DEST="${TPQ_HOME:-$DEFAULT_HOME}"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

tk_hint() {
    if [ "$OS" = "Darwin" ]; then
        echo "  Install Python from https://www.python.org/downloads/ (includes Tk),"
        echo "  or with Homebrew: brew install python python-tk"
    elif command -v apt-get >/dev/null 2>&1; then
        echo "  sudo apt install python3 python3-venv python3-tk"
    elif command -v dnf >/dev/null 2>&1; then
        echo "  sudo dnf install python3 python3-tkinter"
    elif command -v pacman >/dev/null 2>&1; then
        echo "  sudo pacman -S python tk"
    elif command -v zypper >/dev/null 2>&1; then
        echo "  sudo zypper install python3 python3-tk"
    else
        echo "  Install Python 3.9+ with tkinter using your package manager."
    fi
}

# --- find a Python 3.9+ that has tkinter and venv
PY=""
for cand in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if command -v "$cand" >/dev/null 2>&1 &&
        "$cand" -c 'import sys, tkinter, venv; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
        PY="$(command -v "$cand")"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.9+ with tkinter and venv was not found. Install it first:" >&2
    tk_hint >&2
    exit 1
fi
say "Using $("$PY" --version 2>&1) at $PY"

# --- get the sources
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -n "${TPQ_SRC_DIR:-}" ]; then
    SRC="$TPQ_SRC_DIR"
else
    say "Downloading $REPO ($BRANCH)"
    command -v curl >/dev/null 2>&1 || die "curl is required"
    curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar -xz -C "$TMP"
    SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)/python"
fi
[ -f "$SRC/run.py" ] || die "sources not found in $SRC"

say "Installing to $DEST"
mkdir -p "$DEST"
rm -rf "$DEST/app"
cp -R "$SRC" "$DEST/app"

# --- virtual environment and dependencies
if [ ! -x "$DEST/venv/bin/python" ]; then
    "$PY" -m venv "$DEST/venv" || { echo "Can't create a virtual environment. Try:" >&2; tk_hint >&2; exit 1; }
fi
VPY="$DEST/venv/bin/python"
say "Installing dependencies (numpy, Pillow, numba)"
"$VPY" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$VPY" -m pip install --quiet --disable-pip-version-check numpy Pillow
"$VPY" -m pip install --quiet --disable-pip-version-check numba ||
    warn "numba could not be installed: everything works, but quantizing will be much slower"
"$VPY" -m pip install --quiet --disable-pip-version-check tkinterdnd2 >/dev/null 2>&1 ||
    warn "tkinterdnd2 not installed: drag & drop is disabled"

say "Precompiling (takes a few seconds)"
(cd "$DEST/app" && "$VPY" -c 'from tiledpalettequant.core import warmup; warmup()') ||
    warn "precompiling failed, it will happen on first start instead"

# --- launchers
mkdir -p "$BIN_DIR"
cat >"$BIN_DIR/tiledpalettequant" <<EOF
#!/bin/sh
exec "$VPY" "$DEST/app/run.py" "\$@"
EOF
cat >"$BIN_DIR/tiledpalettequant-cli" <<EOF
#!/bin/sh
PYTHONPATH="$DEST/app" exec "$VPY" -m tiledpalettequant cli "\$@"
EOF
cat >"$BIN_DIR/tiledpalettequant-uninstall" <<EOF
#!/bin/sh
TPQ_HOME="$DEST" exec bash "$DEST/app/uninstall.sh"
EOF
chmod +x "$BIN_DIR/tiledpalettequant" "$BIN_DIR/tiledpalettequant-cli" "$BIN_DIR/tiledpalettequant-uninstall"

if [ "$OS" = "Darwin" ]; then
    APP="$HOME/Applications/Tiled Palette Quantizer.app"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
    cat >"$APP/Contents/MacOS/launcher" <<EOF
#!/bin/sh
exec "$VPY" "$DEST/app/run.py" "\$@"
EOF
    chmod +x "$APP/Contents/MacOS/launcher"
    cat >"$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Tiled Palette Quantizer</string>
    <key>CFBundleIdentifier</key><string>io.github.drak3dev.tiledpalettequant</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
    say "App created: $APP"
else
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS"
    cat >"$APPS/tiledpalettequant.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tiled Palette Quantizer
Comment=Quantize images to tiles with several small palettes
Exec="$BIN_DIR/tiledpalettequant" %f
Icon=$DEST/app/tiledpalettequant/carina-nebula.png
Terminal=false
Categories=Graphics;
MimeType=image/png;image/bmp;image/gif;image/jpeg;image/webp;
EOF
    say "Menu entry created: $APPS/tiledpalettequant.desktop"
fi

say "Done! Start it with: tiledpalettequant"
say "Uninstall with: tiledpalettequant-uninstall"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in PATH; add it, or run $BIN_DIR/tiledpalettequant directly" ;;
esac
