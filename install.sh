#!/data/data/com.termux/files/usr/bin/bash
# OpenCode UNLIMITED — bootstrap installer
# Thin entry point: checks deps, ensures setup.py is present, then delegates
# everything to setup.py for the full install + daemon control.
# Works on Termux (pkg) and proot-distro Ubuntu (apt). No root, no Docker.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

cprint() { printf '%b%s%b\n' "$2" "$1" "$NC"; }

ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    cprint "Error: $ARCH not supported. Requires aarch64/ARM64." "$RED"
    exit 1
fi

echo -e "${BLUE}=== OpenCode UNLIMITED Installer ===${NC}"

# --- dependencies (apt first, pkg fallback) ---
USE_APT=0
command -v apt-get >/dev/null 2>&1 && USE_APT=1

NEEDED=()
for pkg in curl jq proot python3 python; do
    command -v "$pkg" >/dev/null 2>&1 || NEEDED+=("$pkg")
done
if [ "$USE_APT" -eq 0 ]; then
    command -v grun >/dev/null 2>&1 || NEEDED+=("glibc-repo" "glibc-runner")
    command -v termux-chroot >/dev/null 2>&1 || NEEDED+=("termux-tools")
fi

if [ ${#NEEDED[@]} -gt 0 ]; then
    cprint "Installing: ${NEEDED[*]}" "$BLUE"
    if [ "$USE_APT" -eq 1 ]; then
        apt-get update -y
        apt-get install -y "${NEEDED[@]}"
    else
        pkg update -y
        pkg install -y "${NEEDED[@]}"
    fi
fi

# --- directories ---
BASE_DIR="$HOME/.opencode-proxy"
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$BASE_DIR" "$LOCAL_BIN"

# --- copy setup.py into BASE_DIR so opencode-proxy can always find it ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/setup.py" ]; then
    cp "$SCRIPT_DIR/setup.py" "$BASE_DIR/setup.py"
    chmod +x "$BASE_DIR/setup.py"
else
    cprint "setup.py not found next to installer — downloading from GitHub..." "$YELLOW"
    curl -fsSL "https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py" -o "$BASE_DIR/setup.py"
    chmod +x "$BASE_DIR/setup.py"
fi

# --- delegate everything to setup.py ---
cprint "Running setup.py install..." "$BLUE"
python3 "$BASE_DIR/setup.py" install