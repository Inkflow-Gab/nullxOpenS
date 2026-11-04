# OpenCode Termux Unlimited

[![Platform](https://img.shields.io/badge/platform-Android%20%7C%20Termux%20ARM64-green.svg)](#requirements)
[![Engine](https://img.shields.io/badge/engine-opencode2api%20v1.4.6-blue.svg)](https://github.com/jasonxu114514/opencode2api)
[![OpenCode](https://img.shields.io/badge/opencode-v1.19.5-purple.svg)](https://opencode.ai)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-not%20required-brightgreen.svg)](#architectural-notes)

Turnkey setup for running the OpenCode CLI natively on Android (Termux) backed by a rotating Cloudflare WARP egress pool. Eliminates the per-IP rate limits on the anonymous free tier without requiring root, containers, or external servers.

---

## Architecture

```text
┌────────────────────────────────────────────────────────┐
│                      Android Device                    │
│                                                        │
│   OpenCode CLI (TUI / Agent)                           │
│   └── Executed via glibc-runner (grun)                 │
│             │                                          │
│             ▼ HTTP (127.0.0.1:8080/v1)                 │
│                                                        │
│   opencode2api Gateway                                 │
│   ├── Executed inside termux-chroot (DNS bridge)       │
│   ├── Backgrounded via Python double-fork daemon       │
│   ├── Client Fingerprinting:                           │
│   │   ├── Versioned User-Agent                         │
│   │   ├── Canonical descending session ID              │
│   │   ├── Injected 'read' tool declaration             │
│   │   └── Forced stream protocol                       │
│   │                                                    │
│   └── Userspace Cloudflare WARP IPv6 Pool              │
│       ├── Dynamic multi-exit pool                      │
│       └── Transparent egress rotation on HTTP 429/403  │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼ Outbound WireGuard UDP (2408)
            Cloudflare Edge Network
                        │
                        ▼ Rotated Egress /64 Block
            OpenCode Free-Tier Inference
```

---

## Upstream Credits

- [ebouther/opencode-unlimited-proxy](https://github.com/ebouther/opencode-unlimited-proxy): Reverse engineering of OpenCode free-tier request gates, session timestamp layouts, and the multi-egress rotation strategy.
- [jasonxu114514/opencode2api](https://github.com/jasonxu114514/opencode2api): Go gateway engine implementing the OpenAI-compatible bridge and built-in WARP userspace egress manager.
- [OpenCode](https://opencode.ai): Open-source terminal coding assistant.

---

## Why Standard Setup Fails on Android (And How We Fix It)

Upstream projects target standard Linux servers running Docker Compose. On Android Termux:

1. **Docker is unavailable**: Standard Android kernels lack full cgroup and container namespaces for non-root users.
   - *Fix*: We run the statically linked `opencode2api` ARM64 binary directly on Termux userspace.
2. **Go DNS resolution failure (`[::1]:53 connection refused`)**:
   - Go's pure net resolver expects `/etc/resolv.conf`. Android uses `netd` over IPC and has no `/etc/resolv.conf`, causing Go to query `localhost:53` and crash when contacting Cloudflare.
   - *Fix*: We execute the engine through `termux-chroot` (PRoot), which transparently maps `$PREFIX/etc/resolv.conf` into `/etc/resolv.conf` with zero performance penalty.
3. **OpenCode CLI glibc dependency**:
   - OpenCode CLI is distributed as a Bun-compiled executable linked against glibc (`/lib/ld-linux-aarch64.so.1`), while Termux uses Android Bionic libc.
   - *Fix*: Instead of installing a heavy 1GB+ Linux distro rootfs, we use Termux's native `glibc-runner` (`grun`). This allows running the official binary with near-zero overhead.
4. **Process lifecycle preservation**:
   - Background processes spawned directly from a Termux subshell terminate when the session closes.
   - *Fix*: A lightweight Python double-fork spawner detaches standard file descriptors, assigns a clean session ID (`setsid`), and decouples the daemon from terminal hangup signals.

---

## Verified Compatibility Matrix

Tested and verified on Android 12 through Android 15 (aarch64 / Termux v0.118+):

| Component | Target Version | Status |
|---|---|---|
| Proxy Gateway | `opencode2api v1.4.6` | Verified functional |
| Client CLI | `opencode-ai v1.19.5` | Verified functional via `grun` |
| DNS Resolution | Android termux-chroot bridge | Verified (0ms lookup delay) |
| Egress Failover | Cloudflare WARP IPv6 pool | Verified (automatic retry on 429) |
| Terminal UI | OpenCode full interactive TUI | Verified |

---

## Quick Start (One Command)

Run this single command inside Termux:

```bash
curl -fsSL https://raw.githubusercontent.com/leangtg123-art/opencode-termux-unlimited/main/install.sh | bash
```

The script is idempotent. It will:
1. Install system prerequisites (`curl`, `jq`, `proot`, `termux-tools`, `python`, `glibc-runner`).
2. Download and verify the `opencode2api` ARM64 binary.
3. Deploy the double-fork background daemon manager.
4. Configure the proxy with WARP IPv6 rotation (`free_only: true`).
5. Download OpenCode CLI and configure the wrapper script.
6. Generate `~/.config/opencode/opencode.jsonc` pre-linked to `http://127.0.0.1:8080/v1`.
7. Start the daemon and verify connection health.

Once finished, launch OpenCode:

```bash
opencode
```

---

## Manual Step-by-Step Guide

If you prefer building the setup manually:

### 1. Install Base Packages

```bash
pkg update -y
pkg install -y curl jq proot termux-tools python glibc-repo
pkg install -y glibc-runner
```

### 2. Download and Extract Gateway Engine

```bash
mkdir -p ~/.opencode-proxy/bin ~/.local/bin ~/.config/opencode
cd ~/.opencode-proxy

curl -sSL "https://github.com/jasonxu114514/opencode2api/releases/download/v1.4.6/opencode2api_v1.4.6_linux_arm64.tar.gz" -o engine.tar.gz
tar -zxvf engine.tar.gz -C bin/ --strip-components=1 opencode2api_v1.4.6_linux_arm64/opencode2api
chmod +x bin/opencode2api
rm -f engine.tar.gz
```

### 3. Deploy Gateway Configuration

Save to `~/.opencode-proxy/config.json`:

```json
{
  "listen": "127.0.0.1:8080",
  "server_keys": ["local-test-key"],
  "anonymous": true,
  "warp": {
    "enabled": true,
    "pool_size": 4,
    "stack": "ipv6"
  },
  "proxies": ["direct"],
  "upstream": {
    "anonymous": "https://opencode.ai/inference"
  },
  "retry": {
    "max_attempts": 6,
    "timeout_seconds": 180
  },
  "models": {
    "refresh_seconds": 300,
    "free_only": true
  },
  "webui": {
    "enabled": true,
    "listen": "127.0.0.1:8081",
    "username": "admin",
    "password": "changeme-changeme"
  }
}
```

### 4. Create Daemon Controller

Copy `install.sh`'s controller block to `~/.local/bin/opencode-proxy` and make it executable:

```bash
chmod +x ~/.local/bin/opencode-proxy
```

Start the daemon:

```bash
opencode-proxy start
```

Verify status:

```bash
opencode-proxy status
```

### 5. Install OpenCode CLI

```bash
curl -sSL "https://registry.npmjs.org/opencode-linux-arm64/-/opencode-linux-arm64-1.19.5.tgz" -o opencode.tgz
tar -zxvf opencode.tgz -C ~/.local/bin/ --strip-components=2 package/bin/opencode
mv ~/.local/bin/opencode ~/.local/bin/opencode-bin
chmod +x ~/.local/bin/opencode-bin
rm -f opencode.tgz
```

Create the `~/.local/bin/opencode` wrapper:

```bash
cat << 'EOF' > ~/.local/bin/opencode
#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/usr/bin/grun "$HOME/.local/bin/opencode-bin" "$@"
EOF
chmod +x ~/.local/bin/opencode
```

Make sure `export PATH="$HOME/.local/bin:$PATH"` is inside `~/.bashrc`.

### 6. Configure OpenCode Profile

Save to `~/.config/opencode/opencode.jsonc`:

```jsonc
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
```

---

## Gateway Management CLI

Manage the background proxy service at any time:

```bash
# Check daemon state, active exits, and exposed model count
opencode-proxy status

# Start service
opencode-proxy start

# Stop service
opencode-proxy stop

# Restart service
opencode-proxy restart

# Send a verified test request
opencode-proxy test deepseek-v4.1-flash-free

# Stream live access & rotation logs
opencode-proxy logs
```

---

## Active Free Models

The gateway exposes 10 verified free-tier models (filtered from OpenCode's 80 upstream catalog models to prevent 401 unauthorized errors on paid endpoints):

| Model ID | Optimal Use Case | Context Window |
|---|---|---|
| `deepseek-v4.1-flash-free` | Algorithms, code generation, refactoring | 128K |
| `big-pickle` | Multi-step reasoning and project planning | 200K |
| `crouton-alpha-free` | Massive context processing, multimodal docs | 1M |
| `nemotron-3.5-super-vl-free` | NVIDIA Vision-Language tasks | 1M |
| `nemotron-3.5-lightning-free` | Low-latency terminal commands, quick scripts | 262K |
| `glm-5.3-flash-free` | General knowledge queries | 128K |
| `beam-free` | Step-by-step logic and calculations | 1M |
| `mimo-v2.6-flash-free` | Compact quick assistant | 128K |
| `flint-40b-free` | Open-weight foundation model | 128K |
| `pulse-alpha-free` | Multimodal input tasks | 1M |

---

## Connecting External Clients

The gateway provides a standard OpenAI-compatible `/v1` endpoint. You can use it in other tools (Cline, LibreChat, Continue, Chatbox, or custom scripts):

- **API Endpoint**: `http://127.0.0.1:8080/v1`
- **API Key**: `local-test-key`
- **Dashboard**: `http://127.0.0.1:8081` (default: `admin` / `changeme-changeme`)

---

## Troubleshooting

- **Port 8080 already in use**:
  Check running processes with `lsof -i :8080` or `netstat -tlpn`. If an old instance is hanging, run `opencode-proxy stop` followed by `pkill -f opencode2api`.
- **WARP initialization delay**:
  On first start, Cloudflare WARP registration takes 3 to 7 seconds to negotiate keys and obtain IPv6 exit addresses. Check `opencode-proxy logs` to monitor egress assignment.
- **Permission Denied on `/sdcard`**:
  Run `termux-setup-storage` and grant Android storage permissions in the system dialog.

---

## License

[MIT](LICENSE)
