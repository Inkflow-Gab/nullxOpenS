#!/usr/bin/env bash
# Bootstrap installer for OpenCode UNLIMITED.
#
# Installs the packages the setup needs and then hands over to setup.py,
# which does the real work. Works on Termux (pkg) and inside proot-distro
# Ubuntu (apt). No root, no Docker.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

say() { printf '%b%s%b\n' "$2" "$1" "$NC"; }

ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    say "Error: $ARCH is not supported, this needs aarch64." "$RED"
    exit 1
fi

say "OpenCode UNLIMITED installer" "$BLUE"

if command -v apt-get >/dev/null 2>&1; then
    PACKAGES="curl python3"
else
    PACKAGES="curl python proot"
fi

MISSING=""
for pkg in $PACKAGES; do
    command -v "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done

if command -v apt-get >/dev/null 2>&1; then
    command -v grun >/dev/null 2>&1 || MISSING="$MISSING glibc-repo glibc-runner"
    command -v termux-chroot >/dev/null 2>&1 || MISSING="$MISSING termux-tools"
fi

if [ -n "$MISSING" ]; then
    say "Installing:$MISSING" "$BLUE"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y
        # shellcheck disable=SC2086
        apt-get install -y $MISSING
    else
        pkg update -y
        # shellcheck disable=SC2086
        pkg install -y $MISSING
    fi
fi

BASE_DIR="$HOME/.opencode-proxy"
mkdir -p "$BASE_DIR" "$HOME/.local/bin"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/setup.py" ]; then
    cp "$SCRIPT_DIR/setup.py" "$BASE_DIR/setup.py"
    chmod +x "$BASE_DIR/setup.py"
else
    say "setup.py is not next to this script, downloading it..." "$BLUE"
    curl -fsSL "https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py" -o "$BASE_DIR/setup.py"
    chmod +x "$BASE_DIR/setup.py"
fi

say "Running setup.py install" "$BLUE"
python3 "$BASE_DIR/setup.py" install

say "Done." "$GREEN"
say "Start it with: opencode-unlimited"
say "If that is not found, run: export PATH=\"\$HOME/.local/bin:\$PATH\""
