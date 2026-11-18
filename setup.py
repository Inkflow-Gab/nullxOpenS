#!/usr/bin/env python3
"""OpenCode UNLIMITED - installer and controller for the OpenCode proxy.

Installs the opencode2api gateway, the OpenCode CLI and the helper scripts
that connect them, then keeps them running. Works on native Termux and
inside proot-distro Ubuntu.
"""

import argparse
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def info(msg):
    print(f"  {BLUE}->{NC} {msg}")


def ok(msg):
    print(f"  {GREEN}ok{NC} {msg}")


def warn(msg):
    print(f"  {YELLOW}!!{NC} {msg}")


def err(msg):
    print(f"  {RED}xx{NC} {msg}")


def section(title, subtitle=""):
    print()
    print(f"  {BOLD}{CYAN}{title}{NC}")
    if subtitle:
        print(f"  {DIM}{subtitle}{NC}")


def pair(label, value):
    """A dim label with a value, used for the status blocks."""
    print(f"  {DIM}{label:<10}{NC} {value}")


def which(cmd):
    return shutil.which(cmd)


def run(cmd, check=True, capture=False, timeout=None):
    return subprocess.run(cmd, check=check, capture_output=capture, text=True, timeout=timeout)


HOME = Path.home()
BASE_DIR = HOME / ".opencode-proxy"
BIN_DIR = BASE_DIR / "bin"
LOCAL_BIN = HOME / ".local" / "bin"
CONFIG_DIR = HOME / ".config" / "opencode"
PID_FILE = BASE_DIR / "proxy.pid"
LOG_FILE = BASE_DIR / "proxy.log"
CONFIG_FILE = BASE_DIR / "config.json"
ROTATION_FILE = BASE_DIR / "rotation.json"
LANE_PID_FILE = BASE_DIR / "lane.pid"
LANE_STATE_FILE = BASE_DIR / "lane.json"
LANE_LOG_FILE = BASE_DIR / "lane.log"
BACKUP_DIR = BASE_DIR / "backups"
MANAGER_FILE = LOCAL_BIN / "opencode-proxy"
ENGINE_BIN = BIN_DIR / "opencode2api"
OPENCODE_BIN = LOCAL_BIN / "opencode-bin"
OPENCODE_WRAPPER = LOCAL_BIN / "opencode"
OPENCODE_UNLIMITED = LOCAL_BIN / "opencode-unlimited"
OPENCODE_JSONC = CONFIG_DIR / "opencode.jsonc"
BASHRC = HOME / ".bashrc"

ARCH = os.uname().machine
SYSTEM = "darwin" if sys.platform == "darwin" else "linux"

ENGINE_VER = "v1.4.7"
CLI_VER = "1.19.5"
SETUP_URL = "https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py"


def engine_asset():
    """The release file of the gateway that fits this machine."""
    machine = ARCH.lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine
    return f"opencode2api_{ENGINE_VER}_{SYSTEM}_{arch}.tar.gz"


def cli_package():
    """The npm package of the OpenCode CLI that fits this machine."""
    machine = ARCH.lower()
    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        arch = machine
    return f"opencode-{SYSTEM}-{arch}"


ENGINE_URL = (
    "https://github.com/jasonxu114514/opencode2api/releases/download/"
    f"{ENGINE_VER}/{engine_asset()}"
)
CLI_URL = (
    f"https://registry.npmjs.org/{cli_package()}/-/"
    f"{cli_package()}-{CLI_VER}.tgz"
)

API_URL = "http://127.0.0.1:8080"
API_KEY = "local-test-key"
DASHBOARD_URL = "http://127.0.0.1:8081"

PROVIDER = "opencode-unlimited-proxy"
DEFAULT_MODEL = "deepseek-v4.1-flash-free"

TERMUX_ONLY = {"termux-tools", "glibc-repo", "glibc-runner"}
REQUIRED_PKGS = ["curl", "python"]
GLIBC_PKGS = ["glibc-repo", "glibc-runner"]

GATEWAY_CONFIG = {
    "listen": "127.0.0.1:8080",
    "server_keys": [API_KEY],
    "zen_keys": [],
    "go_keys": [],
    "anonymous": True,
    "warp": {
        "enabled": True,
        "pool_size": 4,
        "stack": "ipv6",
        "source_ipv6": "",
    },
    "proxies": ["direct"],
    "proxyfile": "",
    "upstream": {
        "zen": "https://opencode.ai/zen",
        "go": "https://opencode.ai/zen/go",
        "anonymous": "https://opencode.ai/inference",
    },
    "retry": {
        "max_attempts": 6,
        "timeout_seconds": 300,
    },
    "models": {
        "refresh_seconds": 300,
        "protocols": {},
        "free_only": True,
        "active_probes": True,
    },
    "performance": {
        "max_idle_conns": 512,
        "max_idle_conns_per_host": 128,
        "max_conns_per_host": 0,
        "idle_conn_timeout_seconds": 120,
        "connect_timeout_seconds": 10,
        "failure_cooldown_seconds": 15,
        "attempt_timeout_seconds": 0,
        "first_event_timeout_seconds": 0,
        "max_anonymous_exits": 8,
        "free_tier_block_seconds": 900,
    },
    "logging": {
        "level": "info",
        "ring_size": 2000,
        "dump_request_bodies": False,
    },
    "webui": {
        "enabled": True,
        "listen": "127.0.0.1:8081",
        "username": "admin",
        "password": "changeme-changeme",
        "session_ttl_minutes": 720,
    },
    "reasoning": {
        "effort": "medium",
        "effort_by_model": {},
    },
    "rotation": {
        "sota": {
            "alias": "sota",
            "order": [
                "deepseek-v4.1-flash",
                "glm-5.3",
                "grok-4.6",
                "kimi-k3",
                "qwen3.8-max",
            ],
        },
        "sweet": {
            "alias": "sweet",
            "order": [],
        },
        "first_output_seconds": 30,
    },
}

# Free models exposed by the gateway, best first.
MODEL_INFO = {
    "deepseek-v4.1-flash-free": {"use": "Code, algorithms, refactoring", "ctx": "128K", "rank": 1},
    "crouton-alpha-free": {"use": "Massive context, multimodal docs", "ctx": "1M", "rank": 2},
    "nemotron-3.5-super-vl-free": {"use": "Vision-language tasks", "ctx": "1M", "rank": 3},
    "beam-free": {"use": "Step-by-step logic", "ctx": "1M", "rank": 4},
    "pulse-alpha-free": {"use": "Multimodal input", "ctx": "1M", "rank": 5},
    "big-pickle": {"use": "Multi-step reasoning, planning", "ctx": "200K", "rank": 6},
    "nemotron-3.5-lightning-free": {"use": "Low-latency scripts, commands", "ctx": "262K", "rank": 7},
    "glm-5.3-flash-free": {"use": "General knowledge", "ctx": "128K", "rank": 8},
    "flint-40b-free": {"use": "Open-weight foundation", "ctx": "128K", "rank": 9},
    "mimo-v2.6-flash-free": {"use": "Compact quick assistant", "ctx": "128K", "rank": 10},
}

THINKING_MODES = {"low", "medium", "high", "max", "none"}


# --- environment -----------------------------------------------------------


def detect_env():
    """Return 'termux' on native Termux, 'linux' inside proot-distro."""
    if which("apt-get"):
        return "linux"
    if which("pkg"):
        try:
            run(["pkg", "--version"], capture=True)
            return "termux"
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    return "linux"


def packages_for(env):
    """Commands that have to be present for the given environment."""
    pkgs = list(REQUIRED_PKGS)
    if env == "termux":
        pkgs += ["proot", "grun", "termux-chroot"]
    else:
        pkgs = [p for p in pkgs if p != "python"]
        pkgs.append("python3")
    return pkgs


def required_packages(env):
    """Packages that still need installing for the given environment."""
    needed = [p for p in REQUIRED_PKGS if not which(p)]
    if env == "termux":
        if not which("grun"):
            needed += GLIBC_PKGS
        if not which("termux-chroot"):
            needed.append("termux-tools")
        if find_ca_bundle() is None:
            needed.append("ca-certificates")
    else:
        needed = [p for p in needed if p != "python"]
        if not which("python3"):
            needed.append("python3")
        if find_ca_bundle() is None:
            needed.append("ca-certificates")
    return needed


def install_packages(dry_run=False):
    env = detect_env()
    needed = required_packages(env)

    if not needed:
        info("all dependencies are already installed")
        return

    section("installing dependencies")
    info(f"environment: {env}")
    info("packages: " + " ".join(needed))

    if dry_run:
        return

    if env == "termux":
        try:
            run(["pkg", "update", "-y"])
        except subprocess.CalledProcessError:
            warn("pkg update failed, falling back to apt-get")
            env = "linux"

    if env == "termux":
        critical = [p for p in needed if p not in TERMUX_ONLY]
        optional = [p for p in needed if p in TERMUX_ONLY]
        if critical:
            try:
                run(["pkg", "install", "-y"] + critical)
            except subprocess.CalledProcessError as e:
                err(f"pkg install failed: {e}")
                env = "linux"
        for pkg in optional:
            try:
                run(["pkg", "install", "-y", pkg])
            except subprocess.CalledProcessError:
                warn(f"could not install optional package {pkg}")
    else:
        try:
            run(["apt-get", "update", "-y"])
        except subprocess.CalledProcessError:
            warn("apt-get update failed, continuing anyway")
        try:
            run(["apt-get", "install", "-y"] + needed)
        except subprocess.CalledProcessError as e:
            err(f"package install had issues: {e}, continuing anyway")

    ok("dependencies installed")


CA_BUNDLES = [
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/ca-bundle.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
]

# Folders with PEM certificates, used when there is no single bundle file.
CA_DIRS = [
    "/etc/ssl/certs",
    "/system/etc/security/cacerts",
]


def find_ca_bundle():
    """The CA bundle of this system, None when there is none."""
    candidates = list(CA_BUNDLES)
    prefix = os.environ.get("PREFIX")
    if prefix:
        candidates.append(f"{prefix}/etc/ssl/certs/ca-certificates.crt")
    for raw in candidates:
        path = Path(raw)
        try:
            if path.is_file() and path.stat().st_size > 1000:
                return path
        except OSError:
            continue
    return None


def find_ca_dir():
    """A folder with PEM certificates, None when there is none."""
    candidates = list(CA_DIRS)
    prefix = os.environ.get("PREFIX")
    if prefix:
        candidates.append(f"{prefix}/etc/ssl/certs")
    for raw in candidates:
        path = Path(raw)
        try:
            if not path.is_dir():
                continue
            if any(path.glob("*.pem")) or any(path.glob("*.0")):
                return path
        except OSError:
            continue
    return None


def fix_certs():
    """Make sure a CA bundle exists.

    A container without ca-certificates cannot verify the Cloudflare
    certificate and the WARP device never comes up.
    """
    bundle = find_ca_bundle()
    if bundle:
        return bundle

    info("no CA bundle found, installing ca-certificates")
    try:
        if detect_env() == "termux":
            run(["pkg", "install", "-y", "ca-certificates"], check=False)
        else:
            run(["apt-get", "update", "-y"], check=False)
            run(["apt-get", "install", "-y", "ca-certificates"], check=False)
            run(["update-ca-certificates"], check=False)
    except Exception as e:
        warn(f"could not install ca-certificates: {e}")
    return find_ca_bundle()


def do_fix_certs():
    """Install or refresh the CA bundle the gateway needs."""
    section("fixing certificates")
    bundle = find_ca_bundle()
    if bundle:
        ok(f"CA bundle ready: {bundle}")
        pair("size", f"{bundle.stat().st_size} bytes")
    else:
        bundle = fix_certs()
        if bundle:
            ok(f"CA bundle installed: {bundle}")
        else:
            err("no CA bundle could be installed")
            info("inside proot-distro run: apt-get update && apt-get install -y ca-certificates")
            return

    if not health_ok():
        info("restart the gateway: opencode-proxy restart")


def fix_dns():
    """Point /etc/resolv.conf at a public resolver when WARP cannot register.

    Inside proot-distro the resolver is often 127.0.0.1, which the userspace
    WARP client cannot use. Termux is left alone, termux-chroot handles DNS.
    """
    if detect_env() != "linux":
        return

    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return
    try:
        content = resolv.read_text()
    except OSError:
        return

    nameservers = []
    for line in content.splitlines():
        parts = line.strip().split()
        if parts and parts[0] == "nameserver" and len(parts) == 2:
            nameservers.append(parts[1])

    unusable = {"127.0.0.1", "::1", "0.0.0.0"}
    if not nameservers or not all(ns in unusable for ns in nameservers):
        return

    backup = Path("/etc/resolv.conf.opencode-unlimited.bak")
    if not backup.exists():
        try:
            shutil.copy2(resolv, backup)
        except OSError:
            pass
    try:
        resolv.write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
        info("fixed /etc/resolv.conf for WARP DNS")
    except OSError as e:
        warn(f"could not fix /etc/resolv.conf: {e}")


def do_fix_dns():
    section("fix dns")
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        warn("/etc/resolv.conf not found")
        return
    backup = Path("/etc/resolv.conf.opencode-unlimited.bak")
    if not backup.exists():
        try:
            shutil.copy2(resolv, backup)
            info(f"backup written to {backup}")
        except OSError:
            pass
    try:
        resolv.write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
        ok("resolv.conf now points at 1.1.1.1 and 8.8.8.8")
        info("run 'opencode-proxy restart' to apply")
    except OSError as e:
        err(f"could not write /etc/resolv.conf: {e}")


# --- thinking mode ---------------------------------------------------------


def get_thinking_mode():
    """Read the thinking mode out of opencode.jsonc."""
    if not OPENCODE_JSONC.exists():
        return "none", False
    try:
        cfg = json.loads(OPENCODE_JSONC.read_text())
    except (OSError, json.JSONDecodeError):
        return "none", False
    thinking = cfg.get("thinking", {})
    mode = thinking.get("mode", "none")
    return mode, thinking.get("enabled", mode != "none")


def thinking_indicator_plain():
    """Thinking mode as a plain string, safe to put in a config file."""
    mode, enabled = get_thinking_mode()
    if not enabled or mode == "none":
        return "thinking: off"
    return f"thinking: {mode}"


def thinking_indicator():
    """Thinking mode with colour, for terminal output only."""
    mode, enabled = get_thinking_mode()
    if not enabled or mode == "none":
        return f"{DIM}thinking: off{NC}"
    if mode == "max":
        return f"{BOLD}{RED}thinking: max{NC}"
    if mode == "high":
        return f"{BOLD}{YELLOW}thinking: high{NC}"
    if mode == "medium":
        return f"{BLUE}thinking: medium{NC}"
    return f"{DIM}thinking: {mode}{NC}"


def do_thinking(mode=""):
    """Set or show the reasoning effort used by the models."""
    if not mode:
        err("usage: opencode-proxy thinking <mode>")
        info("modes: low, medium, high, max, none")
        info("status: opencode-proxy thinking status")
        return

    mode = mode.lower()

    if mode == "status":
        current, enabled = get_thinking_mode()
        section("thinking mode")
        print(f"  {thinking_indicator()}")
        if not enabled or current == "none":
            info("thinking is off, enable it with: opencode-proxy thinking max")
        else:
            info(f"current mode: {current}")
            if current == "max":
                info("deepthink is active for the DeepSeek models")
            info("restart OpenCode to apply: opencode-unlimited restart")
        return

    if mode not in THINKING_MODES:
        err(f"unknown thinking mode: {mode}")
        info("modes: low, medium, high, max, none")
        return

    section(f"thinking mode: {mode}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config = {}
    if OPENCODE_JSONC.exists():
        try:
            config = json.loads(OPENCODE_JSONC.read_text())
        except (OSError, json.JSONDecodeError):
            config = {}

    config["thinking"] = {"mode": mode, "enabled": mode != "none"}

    models = config.setdefault("provider", {}).setdefault(PROVIDER, {}).setdefault("models", {})
    if DEFAULT_MODEL in models:
        models[DEFAULT_MODEL]["thinking"] = {"mode": mode, "enabled": mode != "none"}

    OPENCODE_JSONC.write_text(json.dumps(config, indent=2))

    # The gateway has its own level for the clients that do not pick one.
    gateway = gateway_config()
    if gateway:
        gateway.setdefault("reasoning", {})["effort"] = mode
        CONFIG_FILE.write_text(json.dumps(gateway, indent=2))

    # The nullx agent keeps its own level, so both stay in step.
    nullx = nullx_config_path()
    if nullx.exists():
        try:
            agent = json.loads(nullx.read_text())
        except (OSError, json.JSONDecodeError):
            agent = {}
        agent["reasoning_effort"] = mode
        nullx.write_text(json.dumps(agent, indent=2))

    ok(f"thinking mode set to {mode}")
    info("restart OpenCode to apply: opencode-unlimited restart")


# --- config files ----------------------------------------------------------


def opencode_config(system_prompt=""):
    """The opencode.jsonc payload that points OpenCode at the local proxy."""
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{PROVIDER}/{DEFAULT_MODEL}",
        "system_prompt": system_prompt,
        "permission": {
            "*": "allow",
            "bash": "allow",
            "read": "allow",
            "write": "allow",
            "edit": "allow",
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "websearch": "allow",
        },
        "provider": {
            PROVIDER: {
                "npm": "@ai-sdk/openai-compatible",
                "name": PROVIDER,
                "options": {"baseURL": f"{API_URL}/v1", "apiKey": API_KEY},
                # The rotation aliases walk a group of models and fail over
                # on quota, rate limit or an upstream failure. They need a Go
                # key in the gateway, so they are offered but not the default.
                "models": {**{name: {} for name in MODEL_INFO}, "sota": {}, "sweet": {}},
            }
        },
    }


def write_config():
    """Write the gateway config.

    Values the user changed are kept, new settings of a newer gateway are
    added, so an upgrade never drops a key someone added by hand.
    """
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    config = json.loads(json.dumps(GATEWAY_CONFIG))

    if CONFIG_FILE.exists():
        try:
            current = json.loads(CONFIG_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            current = {}
        if isinstance(current, dict):
            for key, value in current.items():
                if isinstance(value, dict) and isinstance(config.get(key), dict):
                    merged = dict(config[key])
                    merged.update(value)
                    config[key] = merged
                else:
                    config[key] = value

    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    return config


def nullx_config_path():
    """Where the nullx agent keeps its configuration."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(HOME / ".config")
    return Path(base) / "nullx" / "config.json"


def gateway_config():
    """The gateway config as it is on disk, empty when there is none."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def set_gateway_setting(path, value):
    """Set one setting in the gateway config, path is a list of keys."""
    config = gateway_config()
    node = config
    for key in path[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            return False
    node[path[-1]] = value
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    return True


def gateway_models():
    """The live model list from the gateway, empty when it is unreachable."""
    req = urllib.request.Request(
        f"{API_URL}/v1/models",
        headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
    except Exception:
        return []

    entries = payload.get("data", []) if isinstance(payload, dict) else payload
    models = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id") or entry.get("name")
        if not model_id:
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        cost = entry.get("cost") if isinstance(entry.get("cost"), dict) else metadata.get("cost")
        free = "free" in model_id.lower()
        if isinstance(cost, dict) and cost.get("input") == 0 and cost.get("output") == 0:
            free = True
        context = entry.get("context_window") or metadata.get("context_window") or 0
        models.append({
            "id": model_id,
            "free": free,
            "ctx": context,
            "tools": bool(entry.get("tool_call") or metadata.get("tool_call")),
            "reasoning": bool(entry.get("reasoning") or metadata.get("reasoning")),
            "owner": entry.get("owned_by", ""),
        })
    return models


def write_opencode_config(force=False):
    """Write opencode.jsonc so OpenCode talks to the local gateway."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    prompt = thinking_indicator_plain()

    if OPENCODE_JSONC.exists() and not force:
        try:
            config = json.loads(OPENCODE_JSONC.read_text())
        except (OSError, json.JSONDecodeError):
            config = opencode_config(prompt)

        config["model"] = f"{PROVIDER}/{DEFAULT_MODEL}"
        config.setdefault("provider", {}).setdefault(PROVIDER, {})["options"] = {
            "baseURL": f"{API_URL}/v1",
            "apiKey": API_KEY,
        }
        existing = config.get("system_prompt", "") or ""
        if prompt not in existing:
            config["system_prompt"] = f"{prompt}\n\n{existing}".strip()
        OPENCODE_JSONC.write_text(json.dumps(config, indent=2))
        info("updated opencode.jsonc to route through the local proxy")
        return

    OPENCODE_JSONC.write_text(json.dumps(opencode_config(prompt), indent=2))
    ok("wrote opencode.jsonc routing through the local proxy")


def do_config():
    section("configuration")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if OPENCODE_JSONC.exists():
        info(f"opencode config: {OPENCODE_JSONC}")
        print()
        print(OPENCODE_JSONC.read_text())
    else:
        warn("opencode.jsonc not found, run: opencode-proxy install")

    if CONFIG_FILE.exists():
        info(f"gateway config: {CONFIG_FILE}")
    else:
        warn("gateway config.json not found, run: opencode-proxy install")


def command_dirs():
    """Folders that are already on PATH, so the commands work right away.

    ~/.local/bin is the home for the commands, but a fresh shell does not
    always have it on PATH. Copying them into a system folder that is on
    PATH avoids the "command not found" after the install.
    """
    dirs = []
    prefix = os.environ.get("PREFIX")
    if prefix:
        termux_bin = Path(prefix) / "bin"
        if termux_bin.is_dir():
            dirs.append(termux_bin)
    for raw in ("/usr/local/bin", "/usr/bin"):
        path = Path(raw)
        if path.is_dir() and os.access(path, os.W_OK):
            dirs.append(path)
    return dirs


def install_script(path, content, marker):
    """Write an executable script and copy it into every PATH folder.

    A file that is not ours is never overwritten, so an opencode installed
    by other means keeps working.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, 0o755)

    for extra in command_dirs():
        target = extra / path.name
        if target == path:
            continue
        if target.exists():
            try:
                ours = marker in target.read_text()
            except OSError:
                ours = False
            if not ours:
                warn(f"{target} belongs to something else, leaving it alone")
                continue
        try:
            shutil.copy2(path, target)
            info(f"also installed {target}")
        except OSError as e:
            warn(f"could not install {target}: {e}")


def ensure_path():
    """Make sure ~/.local/bin is on PATH for future shells."""
    if str(LOCAL_BIN) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(LOCAL_BIN) + os.pathsep + os.environ.get("PATH", "")
    line = f'export PATH="{LOCAL_BIN}:$PATH"'

    for rc in (BASHRC, HOME / ".profile", HOME / ".zshrc"):
        if rc == HOME / ".zshrc" and not rc.exists():
            continue
        try:
            content = rc.read_text() if rc.exists() else ""
        except OSError:
            continue
        if ".local/bin" in content:
            continue
        try:
            with open(rc, "a") as f:
                f.write(f"\n{line}\n")
        except OSError as e:
            warn(f"could not update {rc}: {e}")


def check_commands():
    """Tell the user how to reach the commands if they are not on PATH."""
    if which("opencode-unlimited"):
        return True
    warn("opencode-unlimited is not on PATH in this shell")
    info(f"run this now: export PATH=\"{LOCAL_BIN}:$PATH\"")
    info("or open a new terminal, the path is saved in ~/.bashrc and ~/.profile")
    return False


# --- downloads -------------------------------------------------------------


def download(url, dest):
    """Download url to dest with a single line of progress."""
    info(f"downloading {url}")
    shown = -1
    try:
        with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    percent = min(done * 100 / total, 100)
                    if percent - shown >= 1:
                        shown = percent
                        filled = int(30 * percent / 100)
                        bar = "#" * filled + "." * (30 - filled)
                        print(f"\r  [{bar}] {percent:5.1f}% ({done // 1024} KB)", end="", flush=True)
    except Exception as e:
        Path(dest).unlink(missing_ok=True)
        raise RuntimeError(f"could not download {url}: {e}") from e
    print()
    ok("download complete")


def extract_tar(tar_path, dest_dir):
    with tarfile.open(tar_path, "r:gz") as tar:
        try:
            tar.extractall(dest_dir, filter="data")
        except TypeError:
            tar.extractall(dest_dir)


def find_binary(root_dir, name):
    for root, _dirs, files in os.walk(root_dir):
        for entry in files:
            if entry == name:
                return Path(root) / entry
    return None


def installed_engine_version():
    """The version of the gateway on this machine, empty when unknown."""
    stamp = BASE_DIR / "engine.version"
    if stamp.exists():
        try:
            value = stamp.read_text().strip()
            if value:
                return value
        except OSError:
            pass
    health = gateway_health()
    if health:
        return str(health.get("version", "")).strip()
    return ""


def install_engine(dry_run=False, force=False):
    """Download the opencode2api gateway binary."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    current = installed_engine_version()
    if ENGINE_BIN.exists() and not force:
        if current and current == ENGINE_VER:
            info(f"opencode2api {ENGINE_VER} is already installed")
            return
        if current:
            info(f"opencode2api {current} is installed, upgrading to {ENGINE_VER}")
        else:
            info(f"opencode2api is installed, upgrading to {ENGINE_VER}")

    section("installing opencode2api")
    info(f"version: {ENGINE_VER}")

    if dry_run:
        return

    tmp = BASE_DIR / "opencode2api.tar.gz"
    try:
        download(ENGINE_URL, tmp)
    except Exception as e:
        err(str(e))
        info(f"get the file by hand from {ENGINE_URL}")
        info(f"save the binary as {ENGINE_BIN}")
        return
    with tempfile.TemporaryDirectory() as td:
        extract_tar(tmp, td)
        binary = find_binary(td, "opencode2api")
        if not binary:
            err("no opencode2api binary inside the tarball")
            tmp.unlink(missing_ok=True)
            return
        shutil.copy2(binary, ENGINE_BIN)
    os.chmod(ENGINE_BIN, 0o755)
    tmp.unlink(missing_ok=True)
    try:
        (BASE_DIR / "engine.version").write_text(ENGINE_VER + "\n")
    except OSError:
        pass
    ok(f"opencode2api {ENGINE_VER} installed")


def validate_opencode_bin():
    """True when opencode-bin is present and executable."""
    if not OPENCODE_BIN.exists():
        return False
    if OPENCODE_BIN.stat().st_size == 0:
        return False
    return os.access(OPENCODE_BIN, os.X_OK)


def install_opencode_cli(dry_run=False):
    """Download the OpenCode CLI and write the wrapper that launches it."""
    env = detect_env()
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)

    if env == "termux" and not which("grun"):
        warn("grun is missing, the OpenCode CLI needs glibc-runner on Termux")
        warn("install it with: pkg install glibc-repo glibc-runner")

    if not validate_opencode_bin():
        section("installing opencode cli")
        info(f"version: {CLI_VER}")
        if dry_run:
            return
        tmp = LOCAL_BIN / "opencode-cli.tgz"
        try:
            download(CLI_URL, tmp)
        except Exception as e:
            err(str(e))
            info(f"get the file by hand from {CLI_URL}")
            info(f"save the binary as {OPENCODE_BIN}")
            return
        with tempfile.TemporaryDirectory() as td:
            extract_tar(tmp, td)
            binary = find_binary(td, "opencode")
            if not binary:
                err("no opencode binary inside the tarball")
                tmp.unlink(missing_ok=True)
                return
            shutil.copy2(binary, OPENCODE_BIN)
        os.chmod(OPENCODE_BIN, 0o755)
        tmp.unlink(missing_ok=True)
        ok("OpenCode CLI installed")
    else:
        info("OpenCode CLI is already installed")

    write_opencode_wrapper()


def write_opencode_wrapper():
    """Write ~/.local/bin/opencode, the script that starts the CLI.

    On Linux the CLI runs through the local lane: Bun ignores the SOCKS
    variables the WARP client sets, so the wrapper starts a loopback HTTP
    CONNECT proxy and points HTTPS_PROXY at it. The proxy is a child of the
    wrapper, so it disappears with the session.
    """
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    lane = Lanes()
    if detect_env() == "termux":
        # Termux needs glibc-runner, and the binary lives on the same path.
        launcher = 'grun "$HOME/.local/bin/opencode-bin" "$@"'
    else:
        launcher = f'"{OPENCODE_BIN}" "$@"'

    # Termux has no WARP SOCKS listener to compensate for, and proot already
    # reaches the gateway directly, so only native Linux gets the lane.
    lane_hook = lane.wrapper_hook() if detect_env() != "termux" else ""
    lane_note = 'LANE_NOTE="$(python3 "$HOME/.opencode-proxy/setup.py" lane status --quiet 2>/dev/null | head -1)"\n[ -n "$LANE_NOTE" ] && printf "  ${{DIM}}%s${{NC}}\\n" "$LANE_NOTE"' if lane_hook else ""
    install_script(OPENCODE_WRAPPER, f"""#!/usr/bin/env bash
# OpenCode CLI wrapper. Passes every argument through to opencode-bin and
# prints the current thinking mode before handing over.
BOLD='\\033[1m'
DIM='\\033[2m'
CYAN='\\033[0;36m'
NC='\\033[0m'

THINKING_MODE="$(python3 "$HOME/.opencode-proxy/setup.py" thinking status 2>/dev/null \
| grep 'thinking:' | head -1 | sed 's/^ *//')"
echo
printf "  ${{BOLD}}${{CYAN}}OpenCode UNLIMITED${{NC}}  %s\n" "${{THINKING_MODE:-thinking: off}}"
printf "  ${{DIM}}api  {API_URL}/v1${{NC}}\n"
{lane_note}
echo
{lane_hook}
{launcher}
""", "# OpenCode CLI wrapper")


# --- local lane ------------------------------------------------------------
#
# OpenCode runs on Bun, and Bun does not route through the SOCKS listener WARP
# leaves behind. A loopback HTTP CONNECT proxy does work, so the lane is a tiny
# stdlib proxy that the CLI wrapper starts, points HTTPS_PROXY at, and stops
# with the session. The gateway keeps its own egress; the lane only exists so
# the client can reach it over a network OpenCode understands.

LANE_HOST = "127.0.0.1"
LANE_DEFAULT_PORT = 0

LANE_PROXY_FALLBACK = """#!/usr/bin/env python3
import sys

sys.stderr.write("lane_proxy.py is missing; run: opencode-proxy repair\\n")
sys.exit(1)
"""


def lane_sources():
    """Where the lane proxy can come from, best first.

    A checkout has it in scripts/ next to this file. An installed copy of
    setup.py lives in ~/.opencode-proxy, where install already placed the
    proxy itself, so that copy is the source of truth there.
    """
    here = Path(__file__).resolve().parent
    return (here / "scripts" / "lane_proxy.py", BASE_DIR / "lane_proxy.py")


def lane_script():
    """The lane proxy source, or a stub that explains it is missing."""
    for candidate in lane_sources():
        try:
            text = candidate.read_text()
        except OSError:
            continue
        if "def main(" in text:
            return text
    # An install that copied only setup.py still gets a script that says what
    # is wrong instead of a traceback from the wrapper.
    return LANE_PROXY_FALLBACK


def install_lane(dry_run=False):
    """Put the lane proxy next to setup.py so the wrapper can run it."""
    if dry_run:
        info(f"would install the local lane proxy in {BASE_DIR}")
        return
    script = Lanes().ensure()
    ok(f"local lane proxy ready at {script}")


class Lanes:
    """The local lane: a loopback CONNECT proxy for the OpenCode CLI."""

    def __init__(self):
        self.script = BASE_DIR / "lane_proxy.py"
        self.port_file = BASE_DIR / "lane.port"
        self.log_file = LANE_LOG_FILE

    def ensure(self):
        """Write the lane proxy next to this script."""
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        source = lane_script()
        current = self.script.read_text() if self.script.exists() else ""
        if current != source:
            self.script.write_text(source)
            os.chmod(self.script, 0o755)
        return self.script

    def pid(self):
        """The running lane process, or None."""
        if not LANE_PID_FILE.exists():
            return None
        try:
            pid = int(LANE_PID_FILE.read_text().strip())
        except (OSError, ValueError):
            return None
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return pid

    def port(self):
        """The port the lane listens on, or 0 when it is not up."""
        if not self.pid():
            return 0
        try:
            return int(self.port_file.read_text().strip() or 0)
        except (OSError, ValueError):
            return 0

    def start(self):
        """Start the lane and wait for its port, returning it or 0."""
        port = self.port()
        if port:
            return port
        self.ensure()
        try:
            self.port_file.unlink(missing_ok=True)
        except OSError:
            pass
        log_fd = open(self.log_file, "a") if self.log_file else None
        try:
            process = subprocess.Popen(
                [sys.executable, str(self.script), "0", "--port-file", str(self.port_file)],
                stdout=subprocess.DEVNULL,
                stderr=log_fd or subprocess.DEVNULL,
                start_new_session=True,
            )
        finally:
            if log_fd:
                log_fd.close()
        LANE_PID_FILE.write_text(str(process.pid))
        for _ in range(50):
            try:
                port = int(self.port_file.read_text().strip() or 0)
            except (OSError, ValueError):
                port = 0
            if port:
                return port
            if process.poll() is not None:
                return 0
            time.sleep(0.1)
        return 0

    def stop(self):
        """Stop the lane process and forget its state."""
        pid = self.pid()
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
        for path in (LANE_PID_FILE, self.port_file):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        return pid

    def wrapper_hook(self):
        """The bash block the CLI wrapper uses to start and use the lane."""
        return """
# Start the local lane: Bun does not use the WARP SOCKS listener, so the CLI
# talks to a loopback HTTP CONNECT proxy instead.
LANE_PID=""
LANE_PORT=""
LANE_DIR="$HOME/.opencode-proxy"
if command -v python3 >/dev/null 2>&1 && [ -d "$LANE_DIR" ]; then
    python3 "$HOME/.opencode-proxy/setup.py" lane ensure >/dev/null 2>&1
    LANE_PORT_FILE="$HOME/.opencode-proxy/lane.port"
    rm -f "$LANE_PORT_FILE"
    python3 "$HOME/.opencode-proxy/lane_proxy.py" 0 --port-file "$LANE_PORT_FILE" \\
        >>"$HOME/.opencode-proxy/lane.log" 2>&1 &
    LANE_PID=$!
    for _ in $(seq 1 50); do
        if [ -s "$LANE_PORT_FILE" ]; then
            LANE_PORT="$(cat "$LANE_PORT_FILE")"
            break
        fi
        sleep 0.1
    done
    if [ -n "$LANE_PORT" ]; then
        export HTTPS_PROXY="http://127.0.0.1:$LANE_PORT"
        export HTTP_PROXY="http://127.0.0.1:$LANE_PORT"
        export NO_PROXY="127.0.0.1,localhost"
        export https_proxy="$HTTPS_PROXY"
        export http_proxy="$HTTP_PROXY"
        export no_proxy="$NO_PROXY"
        trap \'[ -n "$LANE_PID" ] && kill "$LANE_PID" 2>/dev/null; rm -f "$LANE_PORT_FILE"\' EXIT INT TERM
    fi
fi
"""


def do_lane(action="status"):
    """Control the local CONNECT lane that the CLI wrapper uses."""
    lanes = Lanes()
    action = (action or "status").lower()
    quiet = "--quiet" in sys.argv
    if action in ("ensure",):
        lanes.ensure()
        return
    if action in ("start", "on"):
        port = lanes.start()
        if port:
            if not quiet:
                section("local lane")
                ok(f"listening on 127.0.0.1:{port}")
                info(f"use it with: HTTPS_PROXY=http://127.0.0.1:{port} opencode")
            else:
                print(f"lane up        : 127.0.0.1:{port}")
        else:
            if not quiet:
                err("the lane did not start")
                info(f"check the log: {LANE_LOG_FILE}")
            else:
                print("lane           : down")
        return
    if action in ("stop", "off"):
        pid = lanes.stop()
        if pid:
            ok(f"lane stopped (pid {pid})")
        else:
            info("the lane was not running")
        return
    if action in ("status", "check"):
        lanes.ensure()
        port = lanes.port()
        pid = lanes.pid()
        if quiet:
            if port:
                print(f"lane up        : 127.0.0.1:{port}")
            return
        section("local lane")
        info("Bun ignores the WARP SOCKS listener, so the CLI uses this proxy")
        if port:
            ok(f"listening on 127.0.0.1:{port}" + (f" (pid {pid})" if pid else ""))
            info("the CLI wrapper starts it on demand and stops it on exit")
        else:
            info("not running")
            info("the CLI wrapper starts it when opencode runs")
            info("start it now with: opencode-proxy lane start")
        return
    err(f"unknown lane action: {action}")
    info("usage: opencode-proxy lane {status|start|stop}")


# --- daemon ----------------------------------------------------------------


def get_pid():
    """PID of the running gateway, if any."""
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        if pid:
            try:
                os.kill(int(pid), 0)
                return int(pid)
            except (ProcessLookupError, ValueError):
                pass
    if which("pgrep"):
        try:
            out = run(["pgrep", "-f", str(ENGINE_BIN)], capture=True)
        except subprocess.CalledProcessError:
            return None
        if out.stdout.strip():
            pid = int(out.stdout.strip().splitlines()[0])
            PID_FILE.write_text(str(pid))
            return pid
    return None


def health_ok():
    """True when the gateway answers, ready or not.

    The gateway answers 503 while it is still starting, for example when the
    WARP pool has no exit yet or the model catalog is still loading. That is
    not a failure, so only a missing answer counts as down.
    """
    try:
        urllib.request.urlopen(API_URL + "/healthz", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def gateway_ready():
    """True when the gateway says it can serve requests."""
    return bool(gateway_health().get("ready"))


def start_daemon(dry_run=False):
    """Start the gateway as a detached background process."""
    pid = get_pid()
    if pid:
        warn(f"already running (pid {pid})")
        return

    section("starting proxy")
    if dry_run:
        return

    fix_dns()
    bundle = fix_certs()

    if detect_env() == "termux":
        cmd = ["termux-chroot", str(ENGINE_BIN), "-config", str(CONFIG_FILE)]
        env = os.environ.copy()
        if bundle:
            env["SSL_CERT_FILE"] = str(bundle)
    else:
        cmd = [str(ENGINE_BIN), "-config", str(CONFIG_FILE)]
        env = os.environ.copy()
        if bundle:
            env["SSL_CERT_FILE"] = str(bundle)
        cert_dir = find_ca_dir()
        if cert_dir:
            env["SSL_CERT_DIR"] = str(cert_dir)

    pid = os.fork()
    if pid > 0:
        for _ in range(15):
            if health_ok():
                ok("proxy is online")
                health = gateway_health()
                if health and not health.get("ready"):
                    issues = ", ".join(health.get("issues") or [])
                    warn("the gateway is still starting" + (f": {issues}" if issues else ""))
                    info("check the free lane with: opencode-proxy bypass")
                info(f"api       : {API_URL}/v1")
                info(f"dashboard : {DASHBOARD_URL}")
                info(f"api key   : {API_KEY}")
                return
            time.sleep(1)
        err("proxy did not come up, check the log with: opencode-proxy logs")
        sys.exit(1)

    # first child: detach and fork again so the daemon outlives the shell
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    devnull = open(os.devnull, "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())
    log_fd = open(LOG_FILE, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        os.execve(cmd[0], cmd, env)
    except Exception as e:
        sys.stderr.write(f"could not start {cmd[0]}: {e}\n")
        os._exit(1)


def stop_daemon(dry_run=False):
    pid = get_pid()
    if not pid:
        info("proxy is not running")
        return

    section("stopping proxy")
    if dry_run:
        return
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        pass
    if which("pkill"):
        try:
            run(["pkill", "-f", str(ENGINE_BIN)])
        except subprocess.CalledProcessError:
            pass
    PID_FILE.unlink(missing_ok=True)
    ok("proxy stopped")


def restart_daemon(dry_run=False):
    stop_daemon(dry_run=True)
    time.sleep(1)
    start_daemon(dry_run=dry_run)


def status_daemon():
    pid = get_pid()
    section("proxy status")
    if not pid:
        err("proxy is stopped")
        return

    ok(f"running (pid {pid})")
    data = gateway_health()
    if data:
        status = data.get("status", "?")
        ready = data.get("ready", False)
        if ready:
            ok(f"status    : {status}")
        else:
            issues = ", ".join(data.get("issues") or [])
            warn(f"status    : {status}" + (f" ({issues})" if issues else ""))
        warp = data.get("warp") or {}
        if warp:
            info(
                f"warp      : {warp.get('status', '?')} "
                f"(active {warp.get('active', '?')}, standby {warp.get('standby', '?')})"
            )
        models = data.get("models", {})
        info(f"models    : {models.get('exposed', '?')} free of {models.get('total', '?')} upstream")
        version = data.get("version")
        if version:
            info(f"version   : {version}")
    else:
        warn("gateway is starting or unreachable")
    wall = wall_state()
    wall_data = wall.get("wall") or {}
    if wall_data.get("open"):
        reset = wall_until_text(wall_data)
        warn("wall      : rotation paused until the allowance resets")
        if reset:
            info(f"resets    : {reset}")
    elif wall["blocks"]:
        info(f"wall      : {wall['blocks']} exit(s) refused, rotating")
    info(f"api       : {API_URL}/v1")
    info(f"dashboard : {DASHBOARD_URL}")


# The free tier is applied to the public address that leaves the gateway, and
# Cloudflare counts a whole /64 as one allowance. A block therefore means that
# /64 is spent, and the next request has to leave from another one.
WALL_EVENT = "free_tier_ip_blocked"
WALL_BREAKER = "anonymous_breaker_open"
SUCCESS_EVENT = "anonymous_attempt_succeeded"

# Transport trouble is not a wall, but it is the other reason a request dies
# mid-answer. Counting it next to the wall keeps the two apart: a rotating
# exit and a broken tunnel look identical to the client.
TRANSPORT_EVENTS = (
    "anonymous_attempt_transport_failed",
    "attempt_transport_failed",
    "stream_failed",
    "proxy_unavailable",
    "request_failed",
    "warp_429_exhausted",
)

# The gateway logs every attempt, so the same block is reported once per
# upstream gate. Two blocks of one scope inside this window are one event.
SAME_BLOCK_SECONDS = 60

# Two different /64s blocked inside this window mean the allowance is not
# following the address. Rotating further only spends the pool and cuts live
# streams, so the right move is to wait for the daily reset.
REWALL_SECONDS = 30 * 60
FREE_WALL_EXITS = 2

# How long a broken scope stays in the rotation state. Older entries do not
# change any decision, they only make the file grow.
SCOPE_RETENTION = 24 * 3600
MAX_SCOPES = 32

# Only the tail of the log matters: the state machine folds the events it has
# not seen yet, and the whole file can grow past a terminal session.
LOG_TAIL_BYTES = 2 * 1024 * 1024


def egress_scope(label):
    """The quota scope of an egress label: a /64 for IPv6, a /32 for IPv4.

    The gateway labels a WARP attempt ``warp:`` plus the masked prefix it
    counted against, and leaves a proxy attempt as the redacted proxy name. A
    bare address is masked the same way, because a new /128 inside the old /64
    is the same exhausted allowance and must not look like a rotation.
    """
    label = str(label or "").strip()
    if not label:
        return ""
    prefix, sep, rest = label.partition(":")
    name = rest if sep and prefix == "warp" else label
    address = name.partition("/")[0]
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        # A proxy route is identified by its redacted name, which is already
        # one scope per node.
        return label
    # The allowance is always a whole /64 on IPv6 and a whole /32 on IPv4, so
    # any prefix the label carries is folded to that width.
    width = 32 if ip.version == 4 else 64
    try:
        network = ipaddress.ip_network(f"{ip}/{width}", strict=False)
    except ValueError:
        return label
    scope = f"warp:{network}"
    return scope


def record_time(record):
    """The time of a log record, or zero when it has none."""
    stamp = str(record.get("time", "")).strip()
    if not stamp:
        return 0.0
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return 0.0


def read_log_lines(offset=0):
    """The complete JSON log lines written after offset.

    Only whole lines are returned, so a line the gateway is still writing is
    read again next time instead of being dropped or half-parsed.
    """
    if not LOG_FILE.exists():
        return [], 0
    try:
        size = LOG_FILE.stat().st_size
    except OSError:
        return [], 0
    if offset < 0 or offset > size:
        offset = 0
    if size - offset > LOG_TAIL_BYTES:
        offset = size - LOG_TAIL_BYTES
    try:
        with LOG_FILE.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()
    except OSError:
        return [], offset
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return [], offset
    consumed = offset + cut + 1
    records = []
    for raw in chunk[: cut + 1].splitlines():
        line = raw.strip()
        if not line.startswith(b"{"):
            continue
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records, consumed


def default_rotation_state():
    """The rotation state of a gateway that has never hit a wall."""
    return {
        "version": 1,
        "offset": 0,
        "updated": 0.0,
        "blocks": 0,
        "successes": 0,
        "last_block": 0.0,
        "last_success": 0.0,
        "scopes": {},
        "last_egress": "",
        "last_egress_address": "",
        "last_egress_at": 0.0,
        "egress_changes": 0,
        "transport": {},
        "breaker": {"open": False, "at": 0.0, "until": 0.0, "pause": ""},
        "wall": {"open": False, "since": 0.0, "until": 0.0, "scopes": [], "cleared_at": 0.0, "reason": ""},
    }


def load_rotation_state():
    """The persisted rotation state, or a fresh one when it is unreadable."""
    state = default_rotation_state()
    if not ROTATION_FILE.exists():
        return state
    try:
        raw = json.loads(ROTATION_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return state
    if not isinstance(raw, dict):
        return state
    for key, value in raw.items():
        if key in ("scopes", "wall", "breaker") and isinstance(value, dict):
            state[key].update(value)
        elif key in state:
            state[key] = value
    if not isinstance(state["scopes"], dict):
        state["scopes"] = {}
    if not isinstance(state["transport"], dict):
        state["transport"] = {}
    if not isinstance(state["wall"].get("scopes"), list):
        state["wall"]["scopes"] = []
    return state


def save_rotation_state(state):
    """Write the rotation state atomically, so a crash cannot truncate it."""
    try:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        state["updated"] = time.time()
        tmp = ROTATION_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, ROTATION_FILE)
        return True
    except OSError:
        return False


def note_block(state, scope, stamp, request=""):
    """Fold one free-tier block into the rotation state."""
    scope = scope or "unknown"
    state["blocks"] = int(state.get("blocks", 0) or 0) + 1
    state["last_block"] = max(float(state.get("last_block", 0) or 0), stamp)
    scopes = state["scopes"]
    entry = scopes.get(scope) or {"scope": scope, "blocks": 0, "first": stamp, "last": stamp, "success": 0.0}
    # The gateway logs one block per upstream gate, so a burst for the same
    # scope is one wall event, not one per gate.
    if stamp - float(entry.get("last", 0) or 0) > SAME_BLOCK_SECONDS or not entry.get("blocks"):
        entry["blocks"] = int(entry.get("blocks", 0) or 0) + 1
        entry.setdefault("first", stamp)
    entry["last"] = stamp
    entry["request"] = request
    scopes[scope] = entry
    return entry


def note_success(state, scope, stamp):
    """Fold one accepted free-lane attempt into the rotation state."""
    state["successes"] = int(state.get("successes", 0) or 0) + 1
    state["last_success"] = max(float(state.get("last_success", 0) or 0), stamp)
    if scope:
        scopes = state["scopes"]
        entry = scopes.get(scope) or {"scope": scope, "blocks": 0, "first": stamp, "last": stamp}
        entry["success"] = stamp
        scopes[scope] = entry
    breaker = state.get("breaker") or {}
    if breaker.get("open") and stamp > float(breaker.get("at", 0) or 0):
        # A request got through, so the lane is not paused any more. The
        # gateway reopens the breaker by itself when it has to.
        breaker["open"] = False
        breaker["until"] = 0.0
    wall = state["wall"]
    if wall.get("open") and stamp > float(wall.get("since", 0) or 0):
        # A request got through after the wall, so the allowance follows the
        # address again. evaluate_rotation closes it once every block is older
        # than this success.
        wall["pending_clear"] = True


def clear_wall(state, stamp, reason):
    """Close the wall and remember why, so the report can explain it."""
    wall = state["wall"]
    wall["open"] = False
    wall["cleared_at"] = stamp
    wall["reason"] = reason


def open_wall(state, now, scopes, since=None):
    """Pause rotation until the daily reset, because addresses no longer help.

    The wall starts at the block that opened it, so a request that is accepted
    afterwards proves the lane is back. It ends at the next 00:00 UTC.
    """
    wall = state["wall"]
    wall["open"] = True
    wall["since"] = since if since else now
    wall["until"] = next_utc_midnight(now).timestamp()
    wall["scopes"] = list(scopes)
    wall["reason"] = "two addresses refused"
    wall["cleared_at"] = 0.0


def prune_scopes(state, stamp):
    """Forget scopes that can no longer change a decision."""
    scopes = state["scopes"]
    for name, entry in list(scopes.items()):
        last = max(float(entry.get("last", 0) or 0), float(entry.get("success", 0) or 0))
        if stamp - last > SCOPE_RETENTION:
            del scopes[name]
    if len(scopes) > MAX_SCOPES:
        ordered = sorted(
            scopes.items(),
            key=lambda item: max(float(item[1].get("last", 0) or 0), float(item[1].get("success", 0) or 0)),
        )
        for name, _ in ordered[: len(scopes) - MAX_SCOPES]:
            del scopes[name]


def fold_rotation(state, records, now=None):
    """Apply the gateway events the rotation state has not seen yet."""
    now = now if now is not None else time.time()
    for record in records:
        event = str(record.get("event", ""))
        stamp = record_time(record) or now
        if event == WALL_EVENT:
            scope = egress_scope(record.get("proxy", ""))
            note_block(state, scope, stamp, str(record.get("request_id", "") or ""))
        elif event == SUCCESS_EVENT:
            scope = egress_scope(record.get("proxy", ""))
            note_success(state, scope, stamp)
        elif event in TRANSPORT_EVENTS:
            transport = state.setdefault("transport", {})
            entry = transport.get(event) or {"count": 0, "last": 0.0, "detail": ""}
            entry["count"] = int(entry.get("count", 0) or 0) + 1
            entry["last"] = max(float(entry.get("last", 0) or 0), stamp)
            detail = str(record.get("error", "") or record.get("status", "") or "").strip()
            if detail:
                entry["detail"] = detail[:160]
            transport[event] = entry
        elif event == WALL_BREAKER:
            breaker = state.setdefault("breaker", {})
            breaker["open"] = True
            breaker["at"] = max(float(breaker.get("at", 0) or 0), stamp)
            breaker["pause"] = str(record.get("paused_for", "") or "")
            breaker.setdefault("until", 0.0)
    return state


def evaluate_rotation(state, now=None):
    """Decide what the free lane is doing from the folded state."""
    now = now if now is not None else time.time()
    wall = state["wall"]
    scopes = state["scopes"]
    last_success = float(state.get("last_success", 0) or 0)
    recent = [
        name for name, entry in scopes.items()
        if float(entry.get("last", 0) or 0) and now - float(entry.get("last", 0) or 0) <= REWALL_SECONDS
    ]
    # A block that arrived before the last accepted request has already been
    # answered by a working exit, so it is history, not evidence about the
    # allowance. This is also what lets the wall close without reopening.
    blocked_recent = [
        name for name in recent
        if float(scopes[name].get("last", 0) or 0) > max(
            float(scopes[name].get("success", 0) or 0), last_success
        )
    ]
    if not wall.get("open") and len(blocked_recent) >= FREE_WALL_EXITS:
        # The wall starts with the last block, not with the moment it was
        # noticed: the log may be folded several minutes later.
        opened = max(float(scopes[name].get("last", 0) or 0) for name in blocked_recent)
        open_wall(state, now, blocked_recent, since=opened)
    if wall.get("open") and now >= float(wall.get("until", 0) or 0):
        # The daily allowance reset. The wall is no longer a reason to hold
        # back, but only a request can prove the lane works again.
        clear_wall(state, now, "the daily reset passed")
    elif wall.get("open") and len(blocked_recent) < FREE_WALL_EXITS and last_success > float(wall.get("since", 0) or 0):
        clear_wall(state, now, "a fresh address answered")
    wall.pop("pending_clear", None)
    breaker = state.get("breaker") or {}
    last_block = float(state.get("last_block", 0) or 0)
    stale = bool(last_block) and now - last_block > REWALL_SECONDS
    state["view"] = {
        "blocks": int(state.get("blocks", 0) or 0),
        "successes": int(state.get("successes", 0) or 0),
        "scopes": sorted(scopes),
        "recent": sorted(blocked_recent),
        "recent_distinct": len(blocked_recent),
        "distinct": len(scopes),
        "last_block": last_block,
        "last_success": last_success,
        "stale": stale,
        "breaker": bool(breaker.get("open")),
        "breaker_pause": str(breaker.get("pause", "") or ""),
        "wall": dict(wall),
        "transport": dict(state.get("transport") or {}),
        "recovered": bool(last_success) and last_success > last_block,
    }
    state["view"]["following"] = bool(state["view"]["wall"].get("open")) or (
        not stale and state["view"]["recent_distinct"] >= FREE_WALL_EXITS
    )
    return state


def rotation_state(refresh=True):
    """The rotation state, after folding whatever the gateway logged since."""
    state = load_rotation_state()
    if refresh:
        records, offset = read_log_lines(int(state.get("offset", 0) or 0))
        if records:
            fold_rotation(state, records)
        state["offset"] = offset
        evaluate_rotation(state)
        prune_scopes(state, time.time())
        save_rotation_state(state)
    else:
        evaluate_rotation(state)
    return state


def wall_state():
    """What the free tier did to this gateway, read from the gateway log.

    The gateway logs the egress scope of every exit the free tier refused, so
    the number of distinct scopes says how many addresses were tried. Two
    different ones inside the rewall window mean the allowance is not
    following the address: only the daily reset clears that.
    """
    view = rotation_state()["view"]
    return {
        "blocks": view["blocks"],
        "egresses": view["scopes"][-8:],
        "distinct": view["distinct"],
        "recent_distinct": view["recent_distinct"],
        "breaker": view["breaker"],
        "breaker_pause": view["breaker_pause"],
        "last_block": view["last_block"],
        "last_success": view["last_success"],
        "stale": view["stale"],
        "following": view["following"],
        "wall": view["wall"],
        "transport": view["transport"],
        "recovered": view["recovered"],
    }


def next_utc_midnight(stamp=None):
    """The next 00:00 UTC after stamp, when the free allowance resets."""
    if stamp is None:
        now = datetime.now(timezone.utc)
    else:
        now = datetime.fromtimestamp(stamp, timezone.utc)
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
    return midnight


def wall_until_text(wall):
    """The reset time of an open wall, as UTC and as the local clock."""
    until = float(wall.get("until", 0) or 0)
    if not until:
        return ""
    moment = datetime.fromtimestamp(until, timezone.utc)
    return f"{moment.strftime('%H:%M UTC')} ({moment.astimezone().strftime('%H:%M')} your time)"


def wall_report():
    """Say where the free allowance stands, and what to do about it."""
    section("free wall")
    state = wall_state()
    wall = state["wall"]

    if not state["blocks"] and not wall.get("open") and not state["breaker"]:
        ok("no free tier block in the log")
        info("the free lane is working")
        return state

    info(f"blocked exits      : {state['blocks']}")
    info(f"distinct addresses : {state['distinct']}")
    if state["egresses"]:
        info("last scopes        : " + ", ".join(state["egresses"][-3:]))
    if state["breaker"]:
        pause = state["breaker_pause"] or "a while"
        warn(f"the gateway paused the free lane for {pause}")

    if wall.get("open"):
        err("rotation is paused until the allowance resets")
        info("two different addresses were refused in a row, so rotating again will not help")
        reset = wall_until_text(wall)
        if reset:
            info(f"the allowance resets at {reset}")
        info("use another provider, or wait for the reset")
    elif wall.get("cleared_at") and wall.get("reason") == "the daily reset passed":
        ok("the daily reset passed, the lane can rotate again")
        info("send a request to confirm: opencode-proxy test")
    elif wall.get("cleared_at"):
        ok(f"the wall cleared: {wall.get('reason')}")
    elif state["stale"]:
        ok("the last block is old, the lane recovered on its own")
    elif state["recovered"]:
        ok("a fresh address answered after the block, the lane recovered")
    else:
        warn("one address was refused, the gateway rotates to the next one")
        info("the gateway handles this on its own, try the request again")

    return state


def rotation_report():
    """Show the persisted rotation state and what it means."""
    section("rotation")
    state = rotation_state()
    view = state["view"]
    wall = view["wall"]
    last = state.get("last_block") or 0
    success = state.get("last_success") or 0
    info(f"tracked scopes : {view['distinct']}")
    info(f"blocked exits  : {view['blocks']}")
    info(f"accepted exits : {view['successes']}")
    if last:
        info(f"last block     : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(last)))}")
    if success:
        info(f"last success   : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(success)))}")
    if view["recent"]:
        info("blocked /64s   : " + ", ".join(name.replace("warp:", "") for name in view["recent"][-4:]))
    if wall.get("open"):
        warn("state: paused until the allowance resets")
        reset = wall_until_text(wall)
        if reset:
            info(f"resets at    : {reset}")
        info("rotation is skipped on purpose; a restart will not help")
    elif wall.get("cleared_at") and wall.get("reason") == "the daily reset passed":
        ok("state: ready to rotate again")
        info("confirm with: opencode-proxy test")
    elif view["stale"]:
        ok("state: idle, the last block is old")
    elif state.get("blocks"):
        warn("state: rotating, the gateway moves to the next exit")
    else:
        ok("state: idle, no block recorded")
    transport = view.get("transport") or {}
    if transport:
        total = sum(int(entry.get("count", 0) or 0) for entry in transport.values())
        info(f"transport     : {total} failure(s) in the last log window")
        for event, entry in sorted(transport.items(), key=lambda kv: -int(kv[1].get("count", 0) or 0))[:3]:
            line = f"  {event.replace('_', ' ')}: {entry.get('count', 0)}"
            detail = str(entry.get("detail", "") or "").strip()
            if detail:
                line += f" ({detail[:60]})"
            info(line)
    if not ROTATION_FILE.exists():
        info("no state file yet, it is written on the first block")
    else:
        info(f"state file     : {ROTATION_FILE}")
    return state


def do_rotation(action=""):
    """Inspect or reset the persisted rotation state."""
    action = (action or "status").lower()
    if action in ("status", "show", ""):
        rotation_report()
        return
    if action in ("reset", "clear"):
        state = default_rotation_state()
        state["offset"] = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0
        save_rotation_state(state)
        ok("rotation state cleared, the log offset was kept")
        info("the gateway rotates on the next block again")
        return
    if action in ("check", "verify"):
        state = rotation_report()
        print()
        wall_report()
        return state
    err(f"unknown rotation action: {action}")
    info("usage: opencode-proxy rotation {status|check|reset}")


def do_wall():
    """Report the free tier wall and what clears it."""
    state = wall_report()
    print()
    rotation_report()
    print()
    if state["blocks"]:
        info("more detail: opencode-proxy logs")
        info("full check: opencode-proxy bypass check")
    return


# Public address echo services. The free tier counts one allowance per /64 on
# IPv6 and per /32 on IPv4, so the scope of the address is what matters, not
# the full address.
EGRESS_ENDPOINTS = (
    "https://api6.ipify.org",
    "https://api64.ipify.org",
    "https://icanhazip.com",
)
EGRESS_TIMEOUT = 6


def public_egress(proxy=""):
    """The public address this machine leaves from, or why it could not tell.

    A SOCKS proxy is used when the gateway config lists one, because that is
    the route the requests take. Nothing is guessed: an answer that is not an
    address is ignored, and the first real answer wins.
    """
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(handler)
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    problem = ""
    for endpoint in EGRESS_ENDPOINTS:
        try:
            request = urllib.request.Request(endpoint, headers={"User-Agent": "opencode-proxy"})
            with opener.open(request, timeout=EGRESS_TIMEOUT) as resp:
                body = resp.read(256).decode("utf-8", errors="replace").strip()
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"
            continue
        try:
            address = ipaddress.ip_address(body)
        except ValueError:
            problem = f"{endpoint} answered {body[:40]!r}, not an address"
            continue
        return address, ""
    return None, problem or "no address echo answered"


def warp_proxy_hint():
    """The SOCKS route the gateway itself uses, when the config names one."""
    config = gateway_config()
    for entry in config.get("proxies") or []:
        text = str(entry or "").strip()
        if text.startswith(("socks5://", "socks5h://")):
            return text
    return ""


def record_egress(scope, address):
    """Remember the last confirmed public scope, and whether it changed."""
    state = load_rotation_state()
    previous = str(state.get("last_egress", "") or "")
    state["last_egress"] = scope
    state["last_egress_address"] = str(address)
    state["last_egress_at"] = time.time()
    state["egress_changes"] = int(state.get("egress_changes", 0) or 0)
    changed = bool(previous) and previous != scope
    if changed:
        state["egress_changes"] += 1
    save_rotation_state(state)
    return previous, changed


def do_egress():
    """Confirm the public egress and whether its quota scope really changed."""
    section("egress")
    config = gateway_config()
    warp = config.get("warp") or {}
    if warp.get("enabled"):
        info(f"warp      : on (stack {warp.get('stack', 'ipv6')}, pool {warp.get('pool_size', 2)})")
    else:
        warn("warp is off, requests leave from this machine's address")

    proxy = warp_proxy_hint()
    if proxy:
        info(f"route     : {proxy}")
    else:
        info("route     : direct")

    address, problem = public_egress(proxy)
    if address is None:
        err("could not read the public address")
        info(problem)
        info("the echo services may be blocked here; the gateway still reports its own exits")
        return
    scope = egress_scope(str(address))
    ok(f"public ip : {address}")
    info(f"quota /64 : {scope.replace('warp:', '')}")

    previous, changed = record_egress(scope, address)
    if not previous:
        info("first confirmation, the next one is compared against this scope")
    elif changed:
        ok(f"the scope changed from {previous.replace('warp:', '')}")
        info("a new /64 means the next request starts with a fresh allowance")
        if (wall_state().get("wall") or {}).get("open"):
            info("the wall is still open until the daily reset; a new scope alone is not proof")
    else:
        warn(f"the scope is the same as the last confirmation ({previous.replace('warp:', '')})")
        info("reconnecting WARP inside the same /64 does not rotate the allowance")

    if address.version == 4 and warp.get("stack") == "ipv6":
        warn("the answer is IPv4 although the stack is ipv6")
        info("the tunnel may be down; the free tier counts the IPv4 /32 in that case")


def gateway_health():
    """The gateway readiness document, empty when it does not answer."""
    try:
        with urllib.request.urlopen(API_URL + "/healthz", timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {}
    except Exception:
        return {}


def wall_note():
    """One line about the free wall, for the reports that already talk."""
    wall = wall_state()
    wall_data = wall.get("wall") or {}
    if wall_data.get("open"):
        reset = wall_until_text(wall_data)
        err("the free tier is refusing every address")
        info(("the allowance resets at " + reset) if reset else "the allowance resets at 00:00 UTC")
        info("rotating will not help; use another provider or wait")
    elif wall["blocks"] and not wall["stale"]:
        warn(f"the free tier refused {wall['blocks']} exit(s)")
        info("the gateway rotates to the next address on its own")
    elif wall_data.get("cleared_at"):
        ok("the free wall has cleared, the lane can rotate again")


def bypass_report():
    """Check every part of the free-tier path and name what is broken."""
    section("free tier")

    config = gateway_config()
    anonymous = config.get("anonymous", True)
    free_only = config.get("models", {}).get("free_only", True)
    warp = config.get("warp", {})

    if anonymous:
        ok("anonymous access is on, the gateway uses the free lane")
    else:
        err("anonymous access is off, so no free model can be served")
        info("turn it on with: opencode-proxy bypass enable")

    if free_only:
        ok("only free models are exposed")
    else:
        info("paid models are exposed too, which is fine with a key")

    if warp.get("enabled"):
        ok(f"warp is on (stack {warp.get('stack', 'ipv6')}, pool {warp.get('pool_size', 2)})")
    else:
        warn("warp is off, every request leaves from this machine's address")
        info("the free tier blocks an address that is used too often")
        info("turn it on with: opencode-proxy bypass enable")

    health = gateway_health()
    if not health:
        err("the gateway does not answer on " + API_URL)
        info("start it with: opencode-proxy start")
        wall_note()
        return False

    status = health.get("status", "?")
    ready = health.get("ready", False)
    issues = health.get("issues", []) or []

    if ready:
        ok(f"the gateway is ready (status {status})")
    else:
        err(f"the gateway is not ready (status {status})")

    warp_health = health.get("warp") or {}
    if warp_health:
        active = warp_health.get("active", 0)
        if active > 0:
            ok(f"{active} warp exit(s) are live")
        else:
            err("no warp exit is live, the free tier blocks a single address")
            info("check that UDP port 2408 is open, then: opencode-proxy restart")

    models = health.get("models", {})
    exposed = models.get("exposed", 0)
    total = models.get("total", 0)
    if exposed:
        ok(f"{exposed} free model(s) of {total} upstream")
    else:
        err("the gateway exposes no models")
        info("the catalog may still be loading, wait a moment and run this again")

    if issues:
        for issue in issues:
            if issue == "no_healthy_proxies":
                warn("no proxy is healthy")
                info("try: opencode-proxy fix-dns")
            elif issue == "warp_unavailable":
                warn("warp has no exit")
            elif issue.startswith("model_catalog"):
                warn(issue.replace("_", " "))
            else:
                warn(issue.replace("_", " "))

    problem = log_problem()
    if problem:
        err(problem[0])
        info(problem[1])

    wall_note()

    return ready and exposed > 0


def do_bypass(action="status"):
    """Diagnose and repair the free-tier path."""
    if action in ("enable", "on"):
        config = gateway_config() or {}
        config.setdefault("warp", {})
        config["warp"]["enabled"] = True
        config["warp"].setdefault("stack", "ipv6")
        config["warp"].setdefault("pool_size", 4)
        config["anonymous"] = True
        config.setdefault("models", {})["free_only"] = True
        CONFIG_FILE.write_text(json.dumps(config, indent=2))
        ok("the free lane is on: anonymous access, warp and free models only")
        info("restart the gateway to apply: opencode-proxy restart")
        return

    if action in ("disable", "off"):
        config = gateway_config() or {}
        config.setdefault("warp", {})["enabled"] = False
        CONFIG_FILE.write_text(json.dumps(config, indent=2))
        ok("warp is off")
        info("restart the gateway to apply: opencode-proxy restart")
        return

    if action in ("fix", "repair"):
        wall = wall_state()
        if (wall.get("wall") or {}).get("open"):
            reset = wall_until_text(wall["wall"])
            err("the free tier is refusing every address, a restart will not help")
            if reset:
                info(f"the allowance resets at {reset}")
            info("fix the rest now, so the lane is ready when it opens:")
            fix_certs()
            bypass_report()
            return
        fix_certs()
        do_fix_dns()
        restart_daemon()
        bypass_report()
        return

    if action == "check":
        bypass_report()
        return

    err(f"unknown bypass action: {action}")
    info("usage: opencode-proxy bypass {status|check|enable|disable|fix}")


# --- proxy commands --------------------------------------------------------


def stream_chat(model, prompt):
    """Send one streaming chat request and print the answer as it arrives."""
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }).encode()
    req = urllib.request.Request(
        API_URL + "/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )

    first_token = None
    start = time.time()
    with urllib.request.urlopen(req) as resp:
        for line in resp:
            line = line.decode().strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            content = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if not content:
                continue
            if first_token is None:
                first_token = time.time() - start
            print(content, end="", flush=True)
    print()
    return first_token, time.time() - start


def test_model(model):
    section(f"testing {model}")
    if not health_ok():
        err(f"proxy is not reachable at {API_URL}/healthz")
        info("start it with: opencode-proxy start")
        return
    try:
        stream_chat(model, "Say: Test successful.")
        ok("stream completed")
    except Exception as e:
        err(f"test failed: {e}")


def do_bench(model=""):
    """Measure time to first token for a model."""
    if not model:
        err("usage: opencode-proxy bench <model-id>")
        info(f"example: opencode-proxy bench {DEFAULT_MODEL}")
        return

    section(f"benchmarking {model}")
    try:
        first_token, total = stream_chat(model, "Count from 1 to 5 and say hello.")
    except Exception as e:
        err(f"benchmark failed: {e}")
        return
    ok(f"done in {total:.2f}s")
    if first_token:
        info(f"first token after {first_token:.2f}s")


def show_logs():
    section("proxy logs")
    if not LOG_FILE.exists():
        warn(f"no log file at {LOG_FILE}")
        return
    print(LOG_FILE.read_text(errors="replace")[-5000:])


def do_rate_limit():
    """Look for rate limit events in the gateway log."""
    section("rate limit monitor")
    if not LOG_FILE.exists():
        warn(f"no log file at {LOG_FILE}")
        info("start the proxy first: opencode-proxy start")
        return

    lines = LOG_FILE.read_text(errors="replace").splitlines()
    hits = []
    per_model = {}
    for line in lines:
        low = line.lower()
        if "429" in low or "rate limit" in low or "usage exceeded" in low or "quota" in low:
            hits.append(line)
            for name in MODEL_INFO:
                if name in line:
                    per_model[name] = per_model.get(name, 0) + 1
                    break

    info(f"lines scanned: {len(lines)}")
    info(f"rate limit events: {len(hits)}")
    if not hits:
        ok("no rate limit events in the log")
        return

    print(f"\n{BOLD}recent events{NC}")
    for line in hits[-5:]:
        print(f"  {DIM}{line[:120]}{NC}")
    if per_model:
        print(f"\n{BOLD}models affected{NC}")
        for name, count in sorted(per_model.items(), key=lambda kv: -kv[1]):
            print(f"  {name}: {count}")
    print()
    info("fix dns if the proxy cannot reach the upstream: opencode-proxy fix-dns")
    info("switch model: opencode-proxy model <other-free-model>")
    info("restart the proxy: opencode-proxy restart")


def do_models(subcmd="list"):
    """List the models the gateway offers right now."""
    if subcmd not in ("list", "best"):
        err(f"unknown models subcommand: {subcmd}")
        info("usage: opencode-proxy models {list|best}")
        return

    section("models")
    live = gateway_models()

    if not live:
        warn("the gateway is not reachable, showing the known models")
        info("start it with: opencode-proxy start")
        if subcmd == "best":
            for rank, (name, meta) in enumerate(sorted(MODEL_INFO.items(), key=lambda kv: kv[1]["rank"]), 1):
                if rank > 3:
                    break
                print(f"  {GREEN}{rank}{NC}  {name}  {DIM}{meta['ctx']} - {meta['use']}{NC}")
            return
        print()
        print(f"  {DIM}{'model':<35} {'context':<9} best for{NC}")
        for name, meta in sorted(MODEL_INFO.items(), key=lambda kv: kv[1]["rank"]):
            print(f"  {GREEN}{name:<35}{NC} {BLUE}{meta['ctx']:<9}{NC} {meta['use']}")
        print()
        return

    free = [m for m in live if m["free"]]
    paid = [m for m in live if not m["free"]]
    info(f"{len(live)} models advertised, {len(free)} free")

    if subcmd == "best":
        usable = [m for m in free if m["tools"]] or free
        for rank, model in enumerate(usable[:3], 1):
            tools = " tools" if model["tools"] else ""
            print(f"  {GREEN}{rank}{NC}  {model['id']}  {DIM}{model['ctx'] or '?'}{tools}{NC}")
        print()
        info("switch the default model: opencode-proxy model <model-id>")
        return

    print()
    print(f"  {DIM}{'model':<35} {'context':<9} tools{NC}")
    for model in sorted(free, key=lambda m: (not m["tools"], m["id"])):
        mark = f"{GREEN}yes{NC}" if model["tools"] else f"{DIM}no{NC}"
        ctx = model["ctx"] if model["ctx"] else "?"
        print(f"  {GREEN}{model['id']:<35}{NC} {BLUE}{str(ctx):<9}{NC} {mark}")
    if paid and not gateway_config().get("models", {}).get("free_only", True):
        for model in sorted(paid, key=lambda m: m["id"]):
            mark = f"{GREEN}yes{NC}" if model["tools"] else f"{DIM}no{NC}"
            print(f"  {DIM}{model['id']:<35}{NC} {DIM}{str(model['ctx'] or '?'):<9}{NC} {mark}")
    print()
    info("switch the default model: opencode-proxy model <model-id>")


def do_model(name=""):
    """Change the default model in opencode.jsonc."""
    if not name:
        err("usage: opencode-proxy model <model-id>")
        info("available: " + ", ".join(MODEL_INFO))
        return

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = {}
    if OPENCODE_JSONC.exists():
        try:
            config = json.loads(OPENCODE_JSONC.read_text())
        except (OSError, json.JSONDecodeError):
            config = {}

    config["model"] = f"{PROVIDER}/{name}"
    OPENCODE_JSONC.write_text(json.dumps(config, indent=2))

    # Keep the nullx agent on the same model.
    nullx = nullx_config_path()
    if nullx.exists():
        try:
            agent = json.loads(nullx.read_text())
        except (OSError, json.JSONDecodeError):
            agent = {}
        agent["model"] = name
        nullx.write_text(json.dumps(agent, indent=2))

    ok(f"default model is now {name}")
    info("restart OpenCode to apply: opencode-unlimited restart")


# --- diagnostics -----------------------------------------------------------


def log_problem():
    """Name the failure the gateway logged, with the command that fixes it."""
    if not LOG_FILE.exists():
        return None
    try:
        text = LOG_FILE.read_text(errors="replace")[-20000:]
    except OSError:
        return None

    if "certificate signed by unknown authority" in text or "x509:" in text:
        return ("the gateway could not verify the Cloudflare certificate",
                "run: opencode-proxy fix-certs")
    if "no such host" in text or "server misbehaving" in text:
        return ("the gateway cannot resolve the Cloudflare servers",
                "run: opencode-proxy fix-dns")
    if "/dev/net/tun" in text:
        return ("the WARP device needs a tun interface",
                "check that /dev/net/tun exists on the device")
    if "connection refused" in text or "i/o timeout" in text:
        return ("the gateway cannot reach the upstream",
                "run: opencode-proxy fix-dns, then opencode-proxy restart")
    return None


def do_doctor():
    """Check that every part of the install is in place."""
    section("doctor")
    checks = []

    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("python", py, True))
    checks.append(("architecture", ARCH, supported_platform()))

    env = detect_env()
    checks.append(("environment", env, True))

    for pkg in packages_for(env):
        checks.append((f"package {pkg}", "installed" if which(pkg) else "missing", which(pkg) is not None))

    checks.append(("opencode2api binary", "present" if ENGINE_BIN.exists() else "missing", ENGINE_BIN.exists()))
    checks.append(("opencode cli binary", "present" if OPENCODE_BIN.exists() else "missing", OPENCODE_BIN.exists()))
    checks.append(("opencode wrapper", "present" if OPENCODE_WRAPPER.exists() else "missing", OPENCODE_WRAPPER.exists()))

    on_path = bool(which("opencode-unlimited"))
    checks.append(("commands on PATH", "found" if on_path else f"not in PATH, use {LOCAL_BIN}", on_path))

    checks.append(("gateway config", "present" if CONFIG_FILE.exists() else "missing", CONFIG_FILE.exists()))

    routed = False
    if OPENCODE_JSONC.exists():
        try:
            cfg = json.loads(OPENCODE_JSONC.read_text())
            options = cfg.get("provider", {}).get(PROVIDER, {}).get("options", {})
            routed = options.get("baseURL") == f"{API_URL}/v1"
        except (OSError, json.JSONDecodeError):
            routed = False
    checks.append(("opencode.jsonc routes through the proxy", "routed" if routed else "not routed", routed))

    healthy = health_ok()
    bundle = find_ca_bundle()
    checks.append(("ca certificates", str(bundle) if bundle else "missing", bundle is not None))

    health = gateway_health()
    if health:
        ready = bool(health.get("ready"))
        checks.append((
            "gateway readiness",
            f"{health.get('status', '?')} (ready {ready})",
            ready,
        ))
        warp = health.get("warp") or {}
        if warp:
            checks.append((
                "warp egress",
                f"{warp.get('status', '?')} (active {warp.get('active', '?')}, standby {warp.get('standby', '?')})",
                warp.get("active", 0) > 0,
            ))
        models = health.get("models", {})
        checks.append((
            "free models",
            f"{models.get('exposed', '?')} of {models.get('total', '?')} upstream",
            bool(models.get("exposed")),
        ))
        keys = health.get("keys", {})
        checks.append((
            "anonymous access",
            "on" if keys.get("anonymous") else "off",
            bool(keys.get("anonymous")),
        ))
        issues = health.get("issues") or []
        if issues:
            checks.append(("gateway issues", ", ".join(issues), False))

    wall = wall_state()
    if wall["blocks"]:
        if wall["following"] and not wall["stale"]:
            reset = next_utc_midnight()
            checks.append((
                "free tier wall",
                f"the allowance is not following the address, resets at {reset.strftime('%H:%M UTC')}",
                False,
            ))
        else:
            checks.append((
                "free tier wall",
                f"{wall['blocks']} exit(s) refused, {wall['distinct']} address(es)",
                True,
            ))

    checks.append(("thinking mode", thinking_indicator(), True))

    failed = []
    for name, status, good in checks:
        if good:
            marker = f"{GREEN}ok{NC}"
            value = f"{status}"
        else:
            marker = f"{RED}xx{NC}"
            value = f"{RED}{status}{NC}"
        print(f"  {marker}  {name:<40} {value}")
        if not good:
            failed.append(name)

    print()
    if failed:
        warn(f"{len(failed)} check(s) failed")
        problem = log_problem()
        if problem:
            err(problem[0])
            info(problem[1])
    else:
        ok("everything checks out")

    if not ENGINE_BIN.exists():
        info("install the gateway: python3 setup.py install")
    if not OPENCODE_BIN.exists():
        info("install the CLI: python3 setup.py install")
    if not healthy:
        info("start the gateway: opencode-proxy start")
        info("then fix dns if it still cannot connect: opencode-proxy fix-dns")
    elif health and not health.get("ready"):
        info("the gateway answers but is not ready, check the free lane: opencode-proxy bypass")
        issues = health.get("issues") or []
        if "warp_unavailable" in issues:
            info("no warp exit: check that UDP port 2408 is open, then opencode-proxy restart")
        if "no_healthy_proxies" in issues:
            info("no healthy proxy: opencode-proxy fix-dns, then opencode-proxy restart")
    if not routed:
        info("repoint OpenCode at the proxy: python3 setup.py install")
        info("or inspect the current config: opencode-proxy config")
    if not on_path:
        info("put the commands back on PATH: opencode-proxy repair")
        info(f"or in this shell: export PATH=\"{LOCAL_BIN}:$PATH\"")
    if bundle is None:
        info("install the CA bundle the gateway needs: opencode-proxy fix-certs")
    if not healthy:
        info("check the free tier in detail: opencode-proxy bypass")


def do_validate():
    """Validate the files this script wrote."""
    section("validation")
    ok_all = True

    if CONFIG_FILE.exists():
        try:
            json.loads(CONFIG_FILE.read_text())
            ok("config.json is valid json")
        except json.JSONDecodeError:
            err("config.json is not valid json")
            ok_all = False
    else:
        warn("config.json is missing")
        ok_all = False

    if OPENCODE_JSONC.exists():
        ok("opencode.jsonc exists")
    else:
        warn("opencode.jsonc is missing")

    for label, path in (("opencode2api binary", ENGINE_BIN), ("opencode cli binary", OPENCODE_BIN)):
        if path.exists():
            ok(f"{label} is present")
        else:
            warn(f"{label} is missing")

    return ok_all


# --- small helpers ---------------------------------------------------------


def do_zoom(delta, reset=False):
    """Change the Termux terminal font size."""
    section("terminal font")
    termux_dir = Path.home() / ".termux"
    termux_dir.mkdir(parents=True, exist_ok=True)
    props = termux_dir / "termux.properties"

    size = 14
    if props.exists():
        try:
            for line in props.read_text().splitlines():
                if line.strip().startswith("font-size"):
                    parts = line.split("=")
                    if len(parts) == 2:
                        size = float(parts[1].strip())
        except (OSError, ValueError):
            pass

    if reset:
        new_size = 14
    else:
        new_size = max(min(size + delta, 32), 8)

    props.write_text(f"font-size = {new_size}\n")
    if which("termux-reload-settings"):
        run(["termux-reload-settings"], check=False)
    ok(f"font size {size} -> {new_size}")


def do_autostart(action=""):
    """Start the proxy automatically when the device boots."""
    section("auto start")
    boot_dir = Path.home() / ".termux" / "boot"
    script = boot_dir / "opencode-proxy-start.sh"

    if not action or action == "status":
        if script.exists():
            ok("enabled")
            info(f"script: {script}")
        else:
            info("disabled")
        if not action:
            info("usage: opencode-proxy autostart {enable|disable|status}")
        return

    action = action.lower()
    if action == "enable":
        boot_dir.mkdir(parents=True, exist_ok=True)
        script.write_text(f"""#!/data/data/com.termux/files/usr/bin/bash
# Start OpenCode UNLIMITED after boot.
sleep 10
{HOME}/.local/bin/opencode-proxy start >/dev/null 2>&1 &
{HOME}/.local/bin/opencode-unlimited start --continue >/dev/null 2>&1 &
""")
        os.chmod(script, 0o755)
        ok("enabled, the proxy starts on the next boot")
        info(f"script: {script}")
        info("this needs Termux with the termux-boot app")
        return

    if action == "disable":
        if script.exists():
            script.unlink()
            ok("disabled")
        else:
            info("it was already disabled")
        return

    err(f"unknown autostart action: {action}")
    info("usage: opencode-proxy autostart {enable|disable|status}")


def do_continue():
    """Resume the previous OpenCode session."""
    if not OPENCODE_WRAPPER.exists():
        err("the opencode wrapper is missing, run: opencode-proxy install")
        return
    section("resuming session")
    info("running: opencode --continue")
    try:
        run([str(OPENCODE_WRAPPER), "--continue"], check=False)
    except KeyboardInterrupt:
        info("session closed")


# --- maintenance -----------------------------------------------------------


def do_update():
    """Fetch the latest setup.py and the newest gateway from GitHub."""
    section("updating")
    try:
        tmp = BASE_DIR / "setup.py.new"
        urllib.request.urlretrieve(SETUP_URL, tmp)
        shutil.copy2(tmp, BASE_DIR / "setup.py")
        shutil.copy2(tmp, Path(__file__).resolve())
        tmp.unlink(missing_ok=True)
        ok("setup.py updated, run the installer again to apply")
    except Exception as e:
        err(f"update failed: {e}")
        return

    install_engine(force=True)
    write_config()
    info("restart the gateway to use the new version: opencode-proxy restart")


def do_backup():
    """Save the configs and this script into a tarball."""
    section("backup")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_DIR / f"opencode-backup-{stamp}.tar.gz"
    items = [CONFIG_FILE, OPENCODE_JSONC, BASE_DIR / "setup.py"]
    with tarfile.open(archive, "w:gz") as tar:
        for item in items:
            if item.exists():
                tar.add(item, arcname=item.name)
    ok(f"backup written to {archive}")


def do_restore(archive_path=""):
    """Restore a backup made by do_backup."""
    section("restore")
    if not archive_path:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backups = sorted(BACKUP_DIR.glob("*.tar.gz"))
        if not backups:
            err(f"no backups in {BACKUP_DIR}")
            return
        archive_path = str(backups[-1])
        info(f"using the latest backup: {archive_path}")

    archive = Path(archive_path)
    if not archive.exists():
        err(f"backup not found: {archive}")
        return

    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(BASE_DIR)
    ok(f"restored from {archive}")
    info("apply it with: opencode-proxy restart")


def do_uninstall():
    """Remove everything this script installed."""
    section("uninstalling")
    stop_daemon()

    for path in (PID_FILE, LOG_FILE, CONFIG_FILE, ROTATION_FILE, LANE_PID_FILE,
                 LANE_STATE_FILE, LANE_LOG_FILE, ENGINE_BIN, OPENCODE_BIN,
                 OPENCODE_WRAPPER, MANAGER_FILE, OPENCODE_UNLIMITED, OPENCODE_JSONC):
        try:
            if path.exists():
                path.unlink()
                info(f"removed {path}")
        except OSError as e:
            warn(f"could not remove {path}: {e}")

    for directory in (BIN_DIR, BACKUP_DIR):
        try:
            if directory.exists():
                shutil.rmtree(directory)
                info(f"removed {directory}")
        except OSError as e:
            warn(f"could not remove {directory}: {e}")

    stamp = BASE_DIR / "engine.version"
    try:
        if stamp.exists():
            stamp.unlink()
    except OSError:
        pass

    # Put the resolver back the way it was, if the fix-dns command changed it.
    backup = Path("/etc/resolv.conf.opencode-unlimited.bak")
    resolv = Path("/etc/resolv.conf")
    if backup.exists() and resolv.exists():
        try:
            shutil.copy2(backup, resolv)
            backup.unlink()
            info("restored /etc/resolv.conf")
        except OSError as e:
            warn(f"could not restore /etc/resolv.conf: {e}")

    ok("uninstall complete")


def do_watchdog():
    """Restart the gateway whenever it stops answering.

    A gateway whose WARP pool lost every exit is restarted too: a fresh
    registration gives the requests a new address, which is what clears a
    free tier that blocked the old one.
    """
    section("watchdog")
    info("watching the proxy, ctrl+c to stop")
    wall = wall_state()
    if (wall.get("wall") or {}).get("open"):
        reset = wall_until_text(wall["wall"])
        warn("the free tier wall is open" + (f" until {reset}" if reset else ""))
        info("the watchdog keeps the gateway up, it does not rotate past the wall")
    try:
        while True:
            health = gateway_health()
            if not health:
                warn("proxy is down, restarting it")
                stop_daemon(dry_run=True)
                time.sleep(1)
                start_daemon(dry_run=True)
            elif not health.get("ready", False):
                issues = health.get("issues") or []
                if "warp_unavailable" in issues or "model_catalog_empty" in issues:
                    warn("the free lane is down (" + ", ".join(issues) + "), restarting it")
                    stop_daemon(dry_run=True)
                    time.sleep(1)
                    start_daemon(dry_run=True)
            time.sleep(30)
    except KeyboardInterrupt:
        info("watchdog stopped")


def do_version():
    section("version")
    info("setup.py    : OpenCode UNLIMITED")
    info(f"gateway     : opencode2api {ENGINE_VER}")
    info(f"cli         : OpenCode CLI {CLI_VER}")
    info(f"architecture: {ARCH}")
    info(f"environment : {detect_env()}")


# --- shell scripts ---------------------------------------------------------

MANAGER_SH = r"""#!/usr/bin/env bash
# opencode-proxy - control the gateway and the OpenCode CLI.
SETUP="$HOME/.opencode-proxy/setup.py"

if [ ! -f "$SETUP" ]; then
    echo "setup.py is missing from $HOME/.opencode-proxy"
    echo "reinstall it with: curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3"
    exit 1
fi

case "$1" in
    start)     python3 "$SETUP" start ;;
    stop)      python3 "$SETUP" stop ;;
    restart)   python3 "$SETUP" restart ;;
    status)    python3 "$SETUP" status ;;
    test)      python3 "$SETUP" test "${2:-deepseek-v4.1-flash-free}" ;;
    bench)     python3 "$SETUP" bench "${2:-deepseek-v4.1-flash-free}" ;;
    logs)      python3 "$SETUP" logs ;;
    update)    python3 "$SETUP" update ;;
    uninstall) python3 "$SETUP" uninstall ;;
    backup)    python3 "$SETUP" backup ;;
    restore)   python3 "$SETUP" restore "${2:-}" ;;
    watchdog)  python3 "$SETUP" watchdog ;;
    version)   python3 "$SETUP" version ;;
    validate)  python3 "$SETUP" validate ;;
    install)   python3 "$SETUP" install ;;
    models)    python3 "$SETUP" models "${2:-list}" ;;
    model)     python3 "$SETUP" model "${2:-}" ;;
    config)    python3 "$SETUP" config ;;
    doctor)    python3 "$SETUP" doctor ;;
    continue)  python3 "$SETUP" continue ;;
    fix-dns)   python3 "$SETUP" fix-dns ;;
    fix-certs) python3 "$SETUP" fix-certs ;;
    zoom-in)   python3 "$SETUP" zoom-in ;;
    zoom-out)  python3 "$SETUP" zoom-out ;;
    zoom-reset) python3 "$SETUP" zoom-reset ;;
    thinking)  python3 "$SETUP" thinking "${2:-}" ;;
    rate-limit) python3 "$SETUP" rate-limit ;;
    autostart) python3 "$SETUP" autostart "${2:-}" ;;
    bypass)    python3 "$SETUP" bypass "${2:-status}" ;;
    wall)      python3 "$SETUP" wall ;;
    rotation)  python3 "$SETUP" rotation "${2:-status}" ;;
    egress)    python3 "$SETUP" egress ;;
    lane)      python3 "$SETUP" lane "${2:-status}" ;;
    *)
        echo "usage: opencode-proxy {install|repair|start|stop|restart|status|test [model]|bench [model]|logs|update|uninstall|backup|restore [file]|watchdog|version|validate|models [list|best]|model <name>|config|doctor|continue|fix-dns|fix-certs|zoom-in|zoom-out|zoom-reset|thinking <mode>|rate-limit|autostart {enable|disable|status}|bypass {status|check|enable|disable|fix}|wall|rotation {status|check|reset}|egress|lane {status|start|stop}}"
        exit 1
        ;;
esac
"""

UNLIMITED_SH = r"""#!/usr/bin/env bash
# OpenCode UNLIMITED - starts the gateway and the OpenCode CLI together.
# Run without arguments for the menu, or with start/stop/restart/status.
BASE_DIR="$HOME/.opencode-proxy"
LOCAL_BIN="$HOME/.local/bin"
SETUP="$BASE_DIR/setup.py"

BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f "$SETUP" ]; then
    echo "setup.py is missing from $BASE_DIR"
    echo "reinstall it with: curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3"
    exit 1
fi

# Fall back to whatever is on PATH when the local copy is gone.
if [ -x "$LOCAL_BIN/opencode-proxy" ]; then
    PROXY="$LOCAL_BIN/opencode-proxy"
elif command -v opencode-proxy >/dev/null 2>&1; then
    PROXY="$(command -v opencode-proxy)"
else
    echo "the opencode-proxy command is missing, run: opencode-proxy repair"
    exit 1
fi

if [ -x "$LOCAL_BIN/opencode" ]; then
    CLI="$LOCAL_BIN/opencode"
elif command -v opencode >/dev/null 2>&1; then
    CLI="$(command -v opencode)"
else
    CLI="$LOCAL_BIN/opencode"
fi

item() {
    printf "  ${GREEN}%2s${NC}  %s\n" "$1" "$2"
}

proxy_healthy() {
    curl -s "http://127.0.0.1:8080/healthz" >/dev/null 2>&1
}

wait_for_proxy() {
    local i=0
    while [ "$i" -lt 15 ]; do
        if proxy_healthy; then
            return 0
        fi
        i=$((i + 1))
        sleep 1
    done
    return 1
}

thinking_mode() {
    python3 "$SETUP" thinking status 2>/dev/null | grep 'thinking:' | head -1 | sed 's/^ *//'
}

show_banner() {
    local title="$1"
    echo
    printf "  ${BOLD}${CYAN}%s${NC}  %s\n" "$title" "$(thinking_mode)"
    printf "  ${DIM}api  http://127.0.0.1:8080/v1${NC}\n"
    printf "  ${DIM}dash http://127.0.0.1:8081${NC}\n"
    echo
}

start_opencode() {
    local cont="$1"
    if ! proxy_healthy; then
        "$PROXY" start
        if ! wait_for_proxy; then
            echo "  ${YELLOW}the proxy did not come up, check 'opencode-proxy logs'${NC}"
            return 1
        fi
    fi
    show_banner "OpenCode UNLIMITED"
    if [ "$cont" = "--continue" ]; then
        exec "$CLI" --continue
    else
        exec "$CLI"
    fi
}

show_menu() {
    command -v clear >/dev/null 2>&1 && clear
    echo
    printf "  ${BOLD}${CYAN}OpenCode UNLIMITED${NC}\n"
    printf "  ${DIM}free models through a rotating WARP exit${NC}\n"
    echo
    item 1  "Start"
    item 2  "Start and resume the last session"
    item 3  "Stop the proxy and the CLI"
    item 4  "Restart the proxy and the CLI"
    item 5  "Status"
    item 6  "Models"
    item 7  "Thinking mode"
    item 8  "Terminal font size"
    item 9  "Fix DNS"
    item 10 "Fix certificates"
    item 11 "Auto start on boot"
    item 12 "Doctor"
    item 13 "Rate limit monitor"
    item 14 "Repair the install"
    item 0  "Quit"
    echo
    printf "  ${BOLD}pick a number:${NC} "
}

models_menu() {
    command -v clear >/dev/null 2>&1 && clear
    echo
    printf "  ${BOLD}${CYAN}Models${NC}\n"
    echo
    item 1 "List the free models"
    item 2 "Show the three best models"
    item 3 "Switch the default model"
    item 4 "Benchmark a model"
    item 0 "Back"
    echo
    printf "  ${BOLD}pick a number:${NC} "
}

if [ $# -gt 0 ]; then
    case "$1" in
        start)
            start_opencode "${2:-}"
            ;;
        stop)
            "$PROXY" stop
            command -v pkill >/dev/null 2>&1 && pkill -f "opencode-bin" 2>/dev/null
            ;;
        restart)
            "$PROXY" stop
            command -v pkill >/dev/null 2>&1 && pkill -f "opencode-bin" 2>/dev/null
            sleep 1
            "$PROXY" start
            if wait_for_proxy; then
                show_banner "OpenCode UNLIMITED"
                exec "$CLI"
            else
                echo "  ${YELLOW}the proxy did not come up, check 'opencode-proxy logs'${NC}"
                exit 1
            fi
            ;;
        status)
            "$PROXY" status
            if command -v pgrep >/dev/null 2>&1 && pgrep -f "opencode-bin" >/dev/null 2>&1; then
                printf "  ${GREEN}ok${NC}  OpenCode CLI is running\n"
            else
                printf "  ${DIM}xx  OpenCode CLI is stopped${NC}\n"
            fi
            ;;
        install)
            python3 "$SETUP" install
            ;;
        *)
            echo "usage: opencode-unlimited {start [--continue]|stop|restart|status|install}"
            echo "       run it without arguments for the menu"
            exit 1
            ;;
    esac
    exit 0
fi

while true; do
    show_menu
    read -r choice
    case "$choice" in
        1) start_opencode "" ; exit 0 ;;
        2) start_opencode "--continue" ; exit 0 ;;
        3) "$PROXY" stop ; command -v pkill >/dev/null 2>&1 && pkill -f "opencode-bin" 2>/dev/null ;;
        4) "$PROXY" stop ; command -v pkill >/dev/null 2>&1 && pkill -f "opencode-bin" 2>/dev/null ; sleep 1 ; "$PROXY" start ;;
        5) "$PROXY" status ;;
        6)
            while true; do
                models_menu
                read -r model_choice
                case "$model_choice" in
                    1) "$PROXY" models list ;;
                    2) "$PROXY" models best ;;
                    3) read -r -p "  ${BOLD}model id:${NC} " name ; "$PROXY" model "$name" ;;
                    4) read -r -p "  ${BOLD}model id:${NC} " name ; "$PROXY" bench "$name" ;;
                    0) break ;;
                    *) echo "  unknown option" ;;
                esac
                read -r -p "  ${DIM}press enter to go back...${NC} " _
            done
            ;;
        7)
            echo
            printf "  ${BOLD}${CYAN}Thinking mode${NC}  %s\n" "$(thinking_mode)"
            echo
            item 1 "Status"
            item 2 "low"
            item 3 "medium"
            item 4 "high"
            item 5 "max"
            item 6 "off"
            item 0 "Back"
            echo
            printf "  ${BOLD}pick a number:${NC} "
            read -r think_choice
            case "$think_choice" in
                1) "$PROXY" thinking status ;;
                2) "$PROXY" thinking low ;;
                3) "$PROXY" thinking medium ;;
                4) "$PROXY" thinking high ;;
                5) "$PROXY" thinking max ;;
                6) "$PROXY" thinking none ;;
            esac
            ;;
        8)
            echo
            printf "  ${BOLD}${CYAN}Terminal font size${NC}\n"
            echo
            item 1 "Bigger"
            item 2 "Smaller"
            item 3 "Reset"
            item 0 "Back"
            echo
            printf "  ${BOLD}pick a number:${NC} "
            read -r zoom_choice
            case "$zoom_choice" in
                1) "$PROXY" zoom-in ;;
                2) "$PROXY" zoom-out ;;
                3) "$PROXY" zoom-reset ;;
            esac
            ;;
        9) "$PROXY" fix-dns ;;
        10) "$PROXY" fix-certs ;;
        11)
            echo
            printf "  ${BOLD}${CYAN}Auto start on boot${NC}\n"
            echo
            item 1 "Status"
            item 2 "Enable"
            item 3 "Disable"
            item 0 "Back"
            echo
            printf "  ${BOLD}pick a number:${NC} "
            read -r boot_choice
            case "$boot_choice" in
                1) "$PROXY" autostart status ;;
                2) "$PROXY" autostart enable ;;
                3) "$PROXY" autostart disable ;;
            esac
            ;;
        12) "$PROXY" doctor ;;
        13) "$PROXY" rate-limit ;;
        14) python3 "$SETUP" repair ;;
        0) exit 0 ;;
        *) echo "  unknown option" ;;
    esac
    read -r -p "  ${DIM}press enter to go back...${NC} " _
done
"""


def write_manager():
    """Write ~/.local/bin/opencode-proxy."""
    install_script(MANAGER_FILE, MANAGER_SH, "# opencode-proxy - control the gateway")


def write_unlimited_launcher():
    """Write ~/.local/bin/opencode-unlimited."""
    install_script(OPENCODE_UNLIMITED, UNLIMITED_SH, "# OpenCode UNLIMITED - starts the gateway")


# --- install ---------------------------------------------------------------


def step(label, func, *args, **kwargs):
    """Run one install step. A failure is reported, it does not abort the rest."""
    try:
        func(*args, **kwargs)
        return True
    except Exception as e:
        err(f"{label} failed: {e}")
        return False


def supported_platform():
    """True when this machine has a build of the gateway and the CLI."""
    machine = ARCH.lower()
    return machine in ("aarch64", "arm64", "x86_64", "amd64")


def do_install():
    if not supported_platform():
        err(f"{ARCH} is not supported, this needs aarch64 or x86_64")
        sys.exit(1)

    section("OpenCode UNLIMITED setup")
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    # Keep a copy of this script in BASE_DIR, the proxy commands need it there.
    local_copy = Path(__file__).resolve()
    if local_copy.is_file():
        shutil.copy2(local_copy, BASE_DIR / "setup.py")
    else:
        try:
            urllib.request.urlretrieve(SETUP_URL, BASE_DIR / "setup.py")
        except Exception:
            warn("could not download setup.py")

    failed = []
    if not step("installing dependencies", install_packages):
        failed.append("dependencies")
    if not step("installing the gateway", install_engine):
        failed.append("gateway")
    if not ENGINE_BIN.exists():
        err("the gateway binary is missing")
        info(f"download it by hand from {ENGINE_URL}")
        info(f"save it as {ENGINE_BIN} and make it executable")
        failed.append("gateway binary")
    if not step("writing the configuration", write_config):
        failed.append("configuration")
    if not step("installing the local lane", install_lane):
        failed.append("local lane")
    if not step("writing the commands", write_manager):
        failed.append("commands")
    if not step("writing the launcher", write_unlimited_launcher):
        failed.append("launcher")
    if not step("installing the OpenCode CLI", install_opencode_cli):
        failed.append("OpenCode CLI")
    if not step("writing the OpenCode configuration", write_opencode_config, True):
        failed.append("OpenCode configuration")
    step("setting PATH", ensure_path)

    section("setup complete")
    if failed:
        warn("these steps did not finish: " + ", ".join(failed))
        info("fix the cause and run: opencode-proxy repair")
    else:
        ok("run 'opencode-unlimited' to start the gateway and the CLI together")
        info("or start them separately: opencode-proxy start, then opencode")
        info("check the install: opencode-proxy doctor")
        info("models: opencode-proxy models list")
    if not which("git"):
        info("git is not installed, it is only needed to clone or update from GitHub")
    check_commands()


def do_repair():
    """Rewrite everything the commands need and put them back on PATH.

    Use this when a command is missing, the config was overwritten or the
    install was interrupted. Nothing is downloaded unless a binary is gone.
    """
    section("repairing")
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    local_copy = Path(__file__).resolve()
    if local_copy.is_file():
        shutil.copy2(local_copy, BASE_DIR / "setup.py")

    if not ENGINE_BIN.exists():
        step("installing the gateway", install_engine)
    if not validate_opencode_bin():
        step("installing the OpenCode CLI", install_opencode_cli)
    else:
        step("writing the wrapper", write_opencode_wrapper)

    step("installing the local lane", install_lane)
    step("writing the configuration", write_config)
    step("writing the commands", write_manager)
    step("writing the launcher", write_unlimited_launcher)
    step("writing the OpenCode configuration", write_opencode_config, True)
    step("setting PATH", ensure_path)

    ok("the commands and the configuration were rewritten")
    if not health_ok():
        info("the gateway is not running, start it with: opencode-proxy start")
    check_commands()


def do_install_dry_run():
    section("dry run")
    install_packages(dry_run=True)
    install_engine(dry_run=True)
    install_opencode_cli(dry_run=True)
    install_lane(dry_run=True)
    info("nothing was changed")


ACTIONS = [
    "install", "repair", "start", "stop", "restart", "status", "test", "bench",
    "logs", "update", "uninstall", "backup", "restore", "watchdog", "version",
    "validate", "dry-run", "models", "model", "config", "doctor", "continue",
    "fix-dns", "fix-certs", "zoom-in", "zoom-out", "zoom-reset", "thinking",
    "rate-limit", "autostart", "bypass", "wall", "rotation", "egress", "lane",
]


def main():
    ap = argparse.ArgumentParser(description="OpenCode UNLIMITED installer and controller")
    ap.add_argument("action", nargs="?", choices=ACTIONS, default="install")
    ap.add_argument("model", nargs="?", default="")
    ap.add_argument("archive", nargs="?", default="")
    args = ap.parse_args()

    action = args.action
    if action == "install":
        do_install()
    elif action == "repair":
        do_repair()
    elif action == "start":
        start_daemon()
    elif action == "stop":
        stop_daemon()
    elif action == "restart":
        restart_daemon()
    elif action == "status":
        status_daemon()
    elif action == "test":
        test_model(args.model or DEFAULT_MODEL)
    elif action == "bench":
        do_bench(args.model)
    elif action == "logs":
        show_logs()
    elif action == "update":
        do_update()
    elif action == "uninstall":
        do_uninstall()
    elif action == "backup":
        do_backup()
    elif action == "restore":
        do_restore(args.archive)
    elif action == "watchdog":
        do_watchdog()
    elif action == "version":
        do_version()
    elif action == "validate":
        do_validate()
    elif action == "dry-run":
        do_install_dry_run()
    elif action == "models":
        do_models(args.model or "list")
    elif action == "model":
        do_model(args.model)
    elif action == "config":
        do_config()
    elif action == "doctor":
        do_doctor()
    elif action == "continue":
        do_continue()
    elif action == "fix-dns":
        do_fix_dns()
    elif action == "fix-certs":
        do_fix_certs()
    elif action == "zoom-in":
        do_zoom(2)
    elif action == "zoom-out":
        do_zoom(-2)
    elif action == "zoom-reset":
        do_zoom(0, reset=True)
    elif action == "thinking":
        do_thinking(args.model)
    elif action == "rate-limit":
        do_rate_limit()
    elif action == "autostart":
        do_autostart(args.model)
    elif action == "bypass":
        do_bypass(args.model or "status")
    elif action == "wall":
        do_wall()
    elif action == "rotation":
        do_rotation(args.model)
    elif action == "egress":
        do_egress()
    elif action == "lane":
        do_lane(args.model)


if __name__ == "__main__":
    main()
