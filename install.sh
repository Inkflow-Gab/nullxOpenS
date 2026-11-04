#!/data/data/com.termux/files/usr/bin/bash
# One-command installer for OpenCode Unlimited on Termux (Android)
# Sets up opencode2api with Cloudflare WARP egress pool & OpenCode CLI

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== OpenCode Unlimited Installer for Termux ===${NC}"

ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo -e "${RED}Error: Architecture $ARCH is not supported. This installer requires aarch64 (ARM64).${NC}"
    exit 1
fi

echo "[*] Checking and installing required packages..."
NEEDED_PKGS=()
for pkg in curl jq proot termux-tools python; do
    if ! command -v "$pkg" >/dev/null 2>&1; then
        NEEDED_PKGS+=("$pkg")
    fi
done

if ! command -v grun >/dev/null 2>&1; then
    NEEDED_PKGS+=("glibc-repo" "glibc-runner")
fi

if [ ${#NEEDED_PKGS[@]} -gt 0 ]; then
    echo "[*] Installing missing dependencies: ${NEEDED_PKGS[*]}"
    pkg update -y
    pkg install -y "${NEEDED_PKGS[@]}"
fi

INSTALL_DIR="$HOME/.opencode-proxy"
BIN_DIR="$INSTALL_DIR/bin"
LOCAL_BIN="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/opencode"

mkdir -p "$BIN_DIR" "$LOCAL_BIN" "$CONFIG_DIR"

# 1. Download opencode2api Go engine
OPENCODE2API_VER="v1.4.6"
ENGINE_URL="https://github.com/jasonxu114514/opencode2api/releases/download/${OPENCODE2API_VER}/opencode2api_${OPENCODE2API_VER}_linux_arm64.tar.gz"

echo "[*] Downloading opencode2api engine (${OPENCODE2API_VER})..."
TMP_ARCHIVE="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/opencode2api.tar.gz"
curl -sSL "$ENGINE_URL" -o "$TMP_ARCHIVE"
tar -zxvf "$TMP_ARCHIVE" -C "$BIN_DIR" --strip-components=1 opencode2api_${OPENCODE2API_VER}_linux_arm64/opencode2api
chmod +x "$BIN_DIR/opencode2api"
rm -f "$TMP_ARCHIVE"

# 2. Write daemon spawner (double-fork to detach cleanly)
cat << 'EOF' > "$INSTALL_DIR/daemon_spawn.py"
#!/data/data/com.termux/files/usr/bin/python3
import os
import sys

def daemonize(cmd, log_file, pid_file):
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)

    sys.stdout.flush()
    sys.stderr.flush()

    with open(os.devnull, 'r') as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())

    log_fd = open(log_file, 'a')
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    try:
        os.execvp(cmd[0], cmd)
    except Exception as e:
        sys.stderr.write(f"Failed to exec {cmd}: {e}\n")
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 4:
        sys.exit(1)
    daemonize(sys.argv[3:], sys.argv[2], sys.argv[1])
EOF
chmod +x "$INSTALL_DIR/daemon_spawn.py"

# 3. Create proxy configuration
cat << 'EOF' > "$INSTALL_DIR/config.json"
{
  "listen": "127.0.0.1:8080",
  "server_keys": [
    "local-test-key"
  ],
  "zen_keys": [],
  "go_keys": [],
  "anonymous": true,
  "warp": {
    "enabled": true,
    "pool_size": 4,
    "stack": "ipv6",
    "source_ipv6": ""
  },
  "proxies": [
    "direct"
  ],
  "proxyfile": "",
  "upstream": {
    "zen": "https://opencode.ai/zen",
    "go": "https://opencode.ai/zen/go",
    "anonymous": "https://opencode.ai/inference"
  },
  "retry": {
    "max_attempts": 6,
    "timeout_seconds": 180
  },
  "models": {
    "refresh_seconds": 300,
    "protocols": {},
    "free_only": true
  },
  "performance": {
    "max_idle_conns": 256,
    "max_idle_conns_per_host": 64,
    "max_conns_per_host": 0,
    "idle_conn_timeout_seconds": 60,
    "connect_timeout_seconds": 10,
    "failure_cooldown_seconds": 15,
    "attempt_timeout_seconds": 0,
    "first_event_timeout_seconds": 0
  },
  "logging": {
    "level": "info",
    "ring_size": 1000,
    "dump_request_bodies": false
  },
  "webui": {
    "enabled": true,
    "listen": "127.0.0.1:8081",
    "username": "admin",
    "password": "changeme-changeme",
    "session_ttl_minutes": 720
  }
}
EOF

# 4. Install opencode-proxy manager CLI
cat << 'EOF' > "$LOCAL_BIN/opencode-proxy"
#!/data/data/com.termux/files/usr/bin/bash
BASE_DIR="$HOME/.opencode-proxy"
BIN="$BASE_DIR/bin/opencode2api"
CONFIG="$BASE_DIR/config.json"
PID_FILE="$BASE_DIR/proxy.pid"
LOG_FILE="$BASE_DIR/proxy.log"
SPAWNER="$BASE_DIR/daemon_spawn.py"
API_URL="http://127.0.0.1:8080"
API_KEY="local-test-key"

get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi
    local found
    found=$(pgrep -f "$BIN" | head -n 1)
    if [ -n "$found" ]; then
        echo "$found" > "$PID_FILE"
        echo "$found"
        return 0
    fi
    return 1
}

start_proxy() {
    local pid
    if pid=$(get_pid); then
        echo "[!] OpenCode Proxy is already running (PID: $pid)."
        return 0
    fi

    echo "[*] Starting OpenCode Proxy daemon..."
    python3 "$SPAWNER" "$PID_FILE" "$LOG_FILE" termux-chroot "$BIN" -config "$CONFIG"

    local count=0
    while [ $count -lt 15 ]; do
        if curl -s "$API_URL/healthz" >/dev/null 2>&1; then
            local active_pid
            active_pid=$(cat "$PID_FILE" 2>/dev/null)
            echo "[+] Proxy online! (PID: $active_pid)"
            echo "    API Endpoint: $API_URL/v1"
            echo "    Dashboard   : http://127.0.0.1:8081"
            echo "    API Key     : $API_KEY"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done

    echo "[-] Proxy failed to start or is taking too long. Check logs with: opencode-proxy logs"
    return 1
}

stop_proxy() {
    local pid
    if pid=$(get_pid); then
        echo "[*] Stopping OpenCode Proxy (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        pkill -f "$BIN" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "[+] Proxy stopped."
    else
        pkill -f "$BIN" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "[*] Proxy is not running."
    fi
}

status_proxy() {
    local pid
    if pid=$(get_pid); then
        echo "[+] OpenCode Proxy: RUNNING (PID: $pid)"
        local health
        health=$(curl -s "$API_URL/healthz" 2>/dev/null)
        if [ -n "$health" ]; then
            local warp_stat models_stat exposed_stat
            warp_stat=$(echo "$health" | jq -r '.warp | "\(.status) (active: \(.active), standby: \(.standby))"' 2>/dev/null)
            models_stat=$(echo "$health" | jq -r '.models.total' 2>/dev/null)
            exposed_stat=$(echo "$health" | jq -r '.models.exposed' 2>/dev/null)
            echo "    WARP Status : $warp_stat"
            echo "    Free Models : $exposed_stat active ($models_stat total upstream)"
            echo "    API Base    : $API_URL/v1"
            echo "    Dashboard   : http://127.0.0.1:8081"
        else
            echo "    API Check   : Initializing or unreachable"
        fi
    else
        echo "[-] OpenCode Proxy: STOPPED"
    fi
}

test_chat() {
    local model="${1:-deepseek-v4.1-flash-free}"
    echo "[*] Sending test prompt to '$model'..."
    curl -s -N -H "Authorization: Bearer $API_KEY" \
         -H "Content-Type: application/json" \
         -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Say: Test successful.\"}],\"stream\":true}" \
         "$API_URL/v1/chat/completions" | while read -r line; do
             if [[ "$line" =~ ^data:\ (.*) ]]; then
                 local json_data="${BASH_REMATCH[1]}"
                 if [ "$json_data" = "[DONE]" ]; then
                     echo -e "\n[+] Stream completed."
                     break
                 fi
                 local content
                 content=$(echo "$json_data" | jq -r '.choices[0].delta.content // empty' 2>/dev/null)
                 if [ -n "$content" ]; then
                     echo -n "$content"
                 fi
             fi
         done
    echo ""
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -n 35 "$LOG_FILE"
    else
        echo "[-] No log file found."
    fi
}

case "$1" in
    start)   start_proxy ;;
    stop)    stop_proxy ;;
    restart) stop_proxy; sleep 1; start_proxy ;;
    status)  status_proxy ;;
    test)    test_chat "$2" ;;
    logs)    show_logs ;;
    *)
        echo "Usage: opencode-proxy {start|stop|restart|status|test [model]|logs}"
        exit 1
        ;;
esac
EOF
chmod +x "$LOCAL_BIN/opencode-proxy"

# 5. Install OpenCode CLI if not present
if [ ! -f "$LOCAL_BIN/opencode-bin" ]; then
    echo "[*] Downloading OpenCode CLI binary..."
    TMP_CLI="${TMPDIR:-/data/data/com.termux/files/usr/tmp}/opencode-cli.tgz"
    curl -sSL "https://registry.npmjs.org/opencode-linux-arm64/-/opencode-linux-arm64-1.19.5.tgz" -o "$TMP_CLI"
    tar -zxvf "$TMP_CLI" -C "$LOCAL_BIN" --strip-components=2 package/bin/opencode
    mv "$LOCAL_BIN/opencode" "$LOCAL_BIN/opencode-bin"
    chmod +x "$LOCAL_BIN/opencode-bin"
    rm -f "$TMP_CLI"

    cat << 'EOF' > "$LOCAL_BIN/opencode"
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/usr/bin/grun "$HOME/.local/bin/opencode-bin" "$@"
EOF
    chmod +x "$LOCAL_BIN/opencode"
fi

# 6. Configure OpenCode CLI to use the proxy
if [ ! -f "$CONFIG_DIR/opencode.jsonc" ]; then
    echo "[*] Configuring OpenCode CLI profile..."
    cat << 'EOF' > "$CONFIG_DIR/opencode.jsonc"
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode-unlimited-proxy/deepseek-v4.1-flash-free",
  "permission": {
    "*": "allow",
    "bash": "allow",
    "read": "allow",
    "write": "allow",
    "edit": "allow",
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "websearch": "allow"
  },
  "provider": {
    "opencode-unlimited-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "opencode-unlimited-proxy",
      "options": {
        "baseURL": "http://127.0.0.1:8080/v1",
        "apiKey": "local-test-key"
      },
      "models": {
        "beam-free": {},
        "big-pickle": {},
        "crouton-alpha-free": {},
        "deepseek-v4.1-flash-free": {},
        "flint-40b-free": {},
        "glm-5.3-flash-free": {},
        "mimo-v2.6-flash-free": {},
        "nemotron-3.5-lightning-free": {},
        "nemotron-3.5-super-vl-free": {},
        "pulse-alpha-free": {}
      }
    }
  }
}
EOF
fi

# 7. Ensure PATH contains ~/.local/bin
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    if ! grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

# 8. Start proxy daemon
echo "[*] Starting proxy daemon..."
"$LOCAL_BIN/opencode-proxy" start

echo -e "\n${GREEN}[✓] Setup complete!${NC}"
echo "Run 'opencode' to start the interactive TUI interface."
echo "Manage the gateway with 'opencode-proxy status' or 'opencode-proxy stop'."
