#!/usr/bin/env bash
# One-command installer for nullx + the OpenCode UNLIMITED gateway.
#
# Works when cloned (bash install.sh) and when piped (curl ... | bash).
# Installs the gateway, the nullx binary, a config, then starts the gateway
# and probes a free model.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
DIM='\033[2m'
NC='\033[0m'

say() { printf '%b%s%b\n' "$2" "$1" "$NC"; }
info() { printf '  %b->%b %s\n' "$BLUE" "$NC" "$1"; }
ok() { printf '  %bok%b %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '  %b!!%b %s\n' "$YELLOW" "$NC" "$1"; }
err() { printf '  %bxx%b %s\n' "$RED" "$NC" "$1"; }

REPO="Inkflow-Gab/nullxOpenS"
RAW="https://raw.githubusercontent.com/$REPO/main"
NULLX_TAG="${NULLX_TAG:-v0.1.0}"
GO_VERSION_REQUIRED="1.24"

BASE_DIR="$HOME/.opencode-proxy"
LOCAL_BIN="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/nullx"
GO_ROOT="$HOME/.nullx/go"

say "nullx + OpenCode UNLIMITED installer" "$BLUE"

# --- architecture ----------------------------------------------------------

ARCH=$(uname -m)
case "$ARCH" in
    aarch64|arm64)
        GOARCH="arm64"
        ASSET="nullx-linux-arm64"
        ;;
    x86_64|amd64)
        GOARCH="amd64"
        ASSET="nullx-linux-amd64"
        ;;
    *)
        err "unsupported architecture: $ARCH (need aarch64 or x86_64)"
        exit 1
        ;;
esac

# --- packages --------------------------------------------------------------

if command -v apt-get >/dev/null 2>&1; then
    PACKAGES="curl python3 ca-certificates tar"
else
    PACKAGES="curl python ca-certificates tar"
fi

MISSING=""
for pkg in $PACKAGES; do
    command -v "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done

if [ -n "$MISSING" ]; then
    info "installing:$MISSING"
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y >/dev/null 2>&1 || true
        # shellcheck disable=SC2086
        apt-get install -y $MISSING
    else
        pkg update -y >/dev/null 2>&1 || true
        # shellcheck disable=SC2086
        pkg install -y $MISSING
    fi
fi

# --- source ----------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
if [ -f "$SCRIPT_DIR/go.mod" ] && [ -f "$SCRIPT_DIR/main.go" ]; then
    SRC_DIR="$SCRIPT_DIR"
    info "using source from $SRC_DIR"
elif [ -f "$SCRIPT_DIR/nullxOpenS/go.mod" ]; then
    SRC_DIR="$SCRIPT_DIR/nullxOpenS"
    info "using source from $SRC_DIR"
else
    SRC_DIR=""
fi

# --- gateway ---------------------------------------------------------------

mkdir -p "$BASE_DIR" "$LOCAL_BIN"
if [ -n "$SRC_DIR" ] && [ -f "$SRC_DIR/setup.py" ]; then
    cp "$SRC_DIR/setup.py" "$BASE_DIR/setup.py"
else
    info "downloading setup.py"
    curl -fsSL "$RAW/setup.py" -o "$BASE_DIR/setup.py"
fi
chmod +x "$BASE_DIR/setup.py"

info "installing the gateway"
python3 "$BASE_DIR/setup.py" install

# --- nullx binary ----------------------------------------------------------

install_release() {
    local url="https://github.com/$REPO/releases/download/$NULLX_TAG/$ASSET"
    info "downloading $ASSET ($NULLX_TAG)"
    if curl -fsSL "$url" -o "$LOCAL_BIN/nullx.tmp"; then
        chmod +x "$LOCAL_BIN/nullx.tmp"
        mv "$LOCAL_BIN/nullx.tmp" "$LOCAL_BIN/nullx"
        return 0
    fi
    rm -f "$LOCAL_BIN/nullx.tmp"
    return 1
}

go_ok() {
    command -v go >/dev/null 2>&1 || return 1
    local version major minor
    version=$(go env GOVERSION 2>/dev/null | sed 's/^go//')
    [ -n "$version" ] || return 0
    major=${version%%.*}
    version=${version#*.}
    minor=${version%%.*}
    [ "$major" -gt 1 ] || { [ "$major" -eq 1 ] && [ "$minor" -ge 24 ]; }
}

ensure_go() {
    go_ok && return 0
    if [ -n "${PREFIX:-}" ] && printf '%s' "$PREFIX" | grep -q com.termux; then
        info "installing Go from Termux packages"
        pkg install -y golang
    else
        local tarball="go1.24.0.linux-$GOARCH.tar.gz"
        info "downloading Go 1.24 for $GOARCH"
        rm -rf "$GO_ROOT"
        mkdir -p "$GO_ROOT"
        curl -fsSL "https://go.dev/dl/$tarball" | tar -C "$GO_ROOT" --strip-components=1 -xz
        export PATH="$GO_ROOT/bin:$PATH"
    fi
    go_ok
}

download_source() {
    local dir=/tmp/nullx-build
    rm -rf "$dir"
    mkdir -p "$dir"
    info "downloading source"
    curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" \
        | tar -xz -C "$dir" --strip-components=1
    SRC_DIR="$dir"
}

build_nullx() {
    if [ -z "$SRC_DIR" ] || [ ! -f "$SRC_DIR/go.mod" ]; then
        download_source
    fi
    if ! ensure_go; then
        err "Go 1.24+ is required to build nullx"
        info "install Go, or download a release binary from:"
        info "https://github.com/$REPO/releases"
        return 1
    fi
    info "building nullx"
    ( cd "$SRC_DIR" && CGO_ENABLED=0 GOOS=linux GOARCH="$GOARCH" \
        go build -trimpath -ldflags "-s -w" -o "$LOCAL_BIN/nullx" . )
}

if ! install_release; then
    warn "release binary not available, building from source"
    if ! build_nullx; then
        err "nullx was not installed"
        exit 1
    fi
fi
ok "nullx -> $LOCAL_BIN/nullx"

# --- PATH ------------------------------------------------------------------

case ":$PATH:" in
    *":$LOCAL_BIN:"*) ;;
    *)
        for rc in "$HOME/.bashrc" "$HOME/.profile"; do
            [ -f "$rc" ] || continue
            grep -q '\.local/bin' "$rc" || printf '\nexport PATH="%s:$PATH"\n' "$LOCAL_BIN" >> "$rc"
        done
        export PATH="$LOCAL_BIN:$PATH"
        ;;
esac

# --- config ----------------------------------------------------------------

mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    "$LOCAL_BIN/nullx" init >/dev/null 2>&1 || true
fi
ok "config -> $CONFIG_DIR/config.json"

# --- start and verify ------------------------------------------------------

if [ -x "$LOCAL_BIN/opencode-proxy" ]; then
    info "starting the gateway"
    "$LOCAL_BIN/opencode-proxy" start >/dev/null 2>&1 || true
fi

info "checking free models"
"$LOCAL_BIN/nullx" doctor || true

echo
ok "ready"
echo
printf '  %bnullx%b                  interactive shell\n' "$GREEN" "$NC"
printf '  %bnullx "fix the tests"%b   one-shot prompt\n' "$GREEN" "$NC"
printf '  %bnullx models -free%b     list free models\n' "$GREEN" "$NC"
printf '  %bnullx doctor%b           end-to-end check\n' "$GREEN" "$NC"
printf '  %bopencode-proxy status%b  gateway status\n' "$GREEN" "$NC"
echo
printf '  %bapi%b http://127.0.0.1:8080/v1\n' "$DIM" "$NC"
printf '  %bdocs%b NULLX.md\n' "$DIM" "$NC"
