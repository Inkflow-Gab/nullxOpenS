#!/data/data/com.termux/files/usr/bin/bash
# OpenCode Termux Unlimited — installer
# Entry point: runs the full setup, then hands off to setup.py for daemon control.
# Works standalone. No root, no Docker, no external server.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

cprint() { printf '%b%s%b\n' "$2" "$1" "$NC"; }

ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    cprint "Error: $ARCH not supported. Requires aarch64/ARM64 (Termux)." "$RED"
    exit 1
fi

echo -e "${BLUE}=== OpenCode Termux Unlimited Installer ===${NC}"

# --- dependencies ---
NEEDED=()
for pkg in curl jq proot termux-tools python; do
    command -v "$pkg" >/dev/null 2>&1 || NEEDED+=("$pkg")
done
command -v grun >/dev/null 2>&1 || NEEDED+=("glibc-repo" "glibc-runner")

if [ ${#NEEDED[@]} -gt 0 ]; then
    cprint "Installing: ${NEEDED[*]}" "$BLUE"
    pkg update -y
    pkg install -y "${NEEDED[@]}"
fi

# --- directories ---
BASE_DIR="$HOME/.opencode-proxy"
BIN_DIR="$BASE_DIR/bin"
LOCAL_BIN="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/opencode"
mkdir -p "$BIN_DIR" "$LOCAL_BIN" "$CONFIG_DIR"

# --- download opencode2api engine ---
ENGINE_VER="v1.4.6"
ENGINE_URL="https://github.com/jasonxu114514/opencode2api/releases/download/${ENGINE_VER}/opencode2api_${ENGINE_VER}_linux_arm64.tar.gz"
TMP_ARCHIVE="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/opencode2api.tar.gz"
cprint "Downloading opencode2api ${ENGINE_VER}..." "$BLUE"
curl -sSL "$ENGINE_URL" -o "$TMP_ARCHIVE"
tar -zxvf "$TMP_ARCHIVE" -C "$BIN_DIR" --strip-components=1 opencode2api_${ENGINE_VER}_linux_arm64/opencode2api
chmod +x "$BIN_DIR/opencode2api"
rm -f "$TMP_ARCHIVE"

# --- drop in setup.py (runtime controller) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/setup.py" ]; then
    cp "$SCRIPT_DIR/setup.py" "$BASE_DIR/setup.py"
    chmod +x "$BASE_DIR/setup.py"
fi

# --- config ---
cat > "$BASE_DIR/config.json" << 'JSON'
{
  "listen": "127.0.0.1:8080",
  "server_keys": ["local-test-key"],
  "zen_keys": [],
  "go_keys": [],
  "anonymous": true,
  "warp": { "enabled": true, "pool_size": 4, "stack": "ipv6", "source_ipv6": "" },
  "proxies": ["direct"],
  "proxyfile": "",
  "upstream": {
    "zen": "https://opencode.ai/zen",
    "go": "https://opencode.ai/zen/go",
    "anonymous": "https://opencode.ai/inference"
  },
  "retry": { "max_attempts": 6, "timeout_seconds": 180 },
  "models": { "refresh_seconds": 300, "protocols": {}, "free_only": true },
  "performance": {
    "max_idle_conns": 256, "max_idle_conns_per_host": 64, "max_conns_per_host": 0,
    "idle_conn_timeout_seconds": 60, "connect_timeout_seconds": 10,
    "failure_cooldown_seconds": 15, "attempt_timeout_seconds": 0, "first_event_timeout_seconds": 0
  },
  "logging": { "level": "info", "ring_size": 1000, "dump_request_bodies": false },
  "webui": {
    "enabled": true, "listen": "127.0.0.1:8081",
    "username": "admin", "password": "changeme-changeme", "session_ttl_minutes": 720
  }
}
JSON

# --- opencode-proxy manager CLI ---
cat > "$LOCAL_BIN/opencode-proxy" << 'SH'
#!/data/data/com.termux/files/usr/bin/bash
SETUP="$HOME/.opencode-proxy/setup.py"
case "$1" in
    start)   python3 "$SETUP" start ;;
    stop)    python3 "$SETUP" stop ;;
    restart) python3 "$SETUP" restart ;;
    status)  python3 "$SETUP" status ;;
    test)    python3 "$SETUP" test "${2:-deepseek-v4.1-flash-free}" ;;
    logs)    python3 "$SETUP" logs ;;
    *) echo "Usage: opencode-proxy {start|stop|restart|status|test [model]|logs}"; exit 1 ;;
esac
SH
chmod +x "$LOCAL_BIN/opencode-proxy"

# --- OpenCode CLI ---
if [ ! -f "$LOCAL_BIN/opencode-bin" ]; then
    cprint "Downloading OpenCode CLI..." "$BLUE"
    TMP_CLI="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/opencode-cli.tgz"
    curl -sSL "https://registry.npmjs.org/opencode-linux-arm64/-/opencode-linux-arm64-1.19.5.tgz" -o "$TMP_CLI"
    tar -zxvf "$TMP_CLI" -C "$LOCAL_BIN" --strip-components=2 package/bin/opencode
    mv "$LOCAL_BIN/opencode" "$LOCAL_BIN/opencode-bin"
    chmod +x "$LOCAL_BIN/opencode-bin"
    rm -f "$TMP_CLI"
fi

cat > "$LOCAL_BIN/opencode" << 'SH'
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/usr/bin/grun "$HOME/.local/bin/opencode-bin" "$@"
SH
chmod +x "$LOCAL_BIN/opencode"

# --- OpenCode client config ---
if [ ! -f "$CONFIG_DIR/opencode.jsonc" ]; then
cat > "$CONFIG_DIR/opencode.jsonc" << 'JSON'
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode-unlimited-proxy/deepseek-v4.1-flash-free",
  "permission": {
    "*": "allow", "bash": "allow", "read": "allow", "write": "allow",
    "edit": "allow", "glob": "allow", "grep": "allow", "list": "allow", "websearch": "allow"
  },
  "provider": {
    "opencode-unlimited-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "opencode-unlimited-proxy",
      "options": { "baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local-test-key" },
      "models": {
        "beam-free": {}, "big-pickle": {}, "crouton-alpha-free": {},
        "deepseek-v4.1-flash-free": {}, "flint-40b-free": {}, "glm-5.3-flash-free": {},
        "mimo-v2.6-flash-free": {}, "nemotron-3.5-lightning-free": {},
        "nemotron-3.5-super-vl-free": {}, "pulse-alpha-free": {}
      }
    }
  }
}
JSON
fi

# --- PATH ---
case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
        if [ -f "$HOME/.bashrc" ] && ! grep -q '.local/bin' "$HOME/.bashrc"; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
        fi
        export PATH="$HOME/.local/bin:$PATH"
        ;;
esac

# --- start daemon ---
cprint "Starting proxy daemon..." "$BLUE"
"$LOCAL_BIN/opencode-proxy" start

echo
cprint "[✓] Setup complete." "$GREEN"
cprint "Run: opencode" "$BLUE"
cprint "Manage: opencode-proxy {start|stop|restart|status|test|logs}" "$BLUE"