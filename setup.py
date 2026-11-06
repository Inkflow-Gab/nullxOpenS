#!/usr/bin/env python3
"""OpenCode UNLIMITED - installer and controller for the OpenCode proxy.

Installs the opencode2api gateway, the OpenCode CLI and the helper scripts
that connect them, then keeps them running. Works on native Termux and
inside proot-distro Ubuntu.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
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
BACKUP_DIR = BASE_DIR / "backups"
MANAGER_FILE = LOCAL_BIN / "opencode-proxy"
ENGINE_BIN = BIN_DIR / "opencode2api"
OPENCODE_BIN = LOCAL_BIN / "opencode-bin"
OPENCODE_WRAPPER = LOCAL_BIN / "opencode"
OPENCODE_UNLIMITED = LOCAL_BIN / "opencode-unlimited"
OPENCODE_JSONC = CONFIG_DIR / "opencode.jsonc"
BASHRC = HOME / ".bashrc"

ENGINE_VER = "v1.4.6"
ENGINE_URL = (
    "https://github.com/jasonxu114514/opencode2api/releases/download/"
    f"{ENGINE_VER}/opencode2api_{ENGINE_VER}_linux_arm64.tar.gz"
)
CLI_VER = "1.19.5"
CLI_URL = (
    "https://registry.npmjs.org/opencode-linux-arm64/-/"
    f"opencode-linux-arm64-{CLI_VER}.tgz"
)
SETUP_URL = "https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py"

API_URL = "http://127.0.0.1:8080"
API_KEY = "local-test-key"
DASHBOARD_URL = "http://127.0.0.1:8081"
ARCH = os.uname().machine

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
        "timeout_seconds": 180,
    },
    "models": {
        "refresh_seconds": 300,
        "protocols": {},
        "free_only": True,
    },
    "performance": {
        "max_idle_conns": 256,
        "max_idle_conns_per_host": 64,
        "max_conns_per_host": 0,
        "idle_conn_timeout_seconds": 60,
        "connect_timeout_seconds": 10,
        "failure_cooldown_seconds": 15,
        "attempt_timeout_seconds": 0,
        "first_event_timeout_seconds": 0,
    },
    "logging": {
        "level": "info",
        "ring_size": 1000,
        "dump_request_bodies": False,
    },
    "webui": {
        "enabled": True,
        "listen": "127.0.0.1:8081",
        "username": "admin",
        "password": "changeme-changeme",
        "session_ttl_minutes": 720,
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
                "models": {name: {} for name in MODEL_INFO},
            }
        },
    }


def write_config():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(GATEWAY_CONFIG, indent=2))


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


def install_engine(dry_run=False):
    """Download the opencode2api gateway binary."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if ENGINE_BIN.exists():
        info("opencode2api is already installed")
        return

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
    ok("opencode2api installed")


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
    """Write ~/.local/bin/opencode, the script that starts the CLI."""
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    if detect_env() == "termux":
        launcher = 'exec grun "$HOME/.local/bin/opencode-bin" "$@"'
    else:
        launcher = f'exec "{OPENCODE_BIN}" "$@"'

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
echo
{launcher}
""", "# OpenCode CLI wrapper")


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
    try:
        urllib.request.urlopen(API_URL + "/healthz", timeout=2)
        return True
    except Exception:
        return False


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
    try:
        data = json.loads(urllib.request.urlopen(API_URL + "/healthz", timeout=3).read().decode())
        warp = data.get("warp", {})
        models = data.get("models", {})
        info(
            f"warp      : {warp.get('status', '?')} "
            f"(active {warp.get('active', '?')}, standby {warp.get('standby', '?')})"
        )
        info(f"models    : {models.get('exposed', '?')} free of {models.get('total', '?')} upstream")
    except Exception:
        warn("gateway is starting or unreachable")
    info(f"api       : {API_URL}/v1")
    info(f"dashboard : {DASHBOARD_URL}")


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
    """Show the free models the gateway exposes."""
    if subcmd not in ("list", "best"):
        err(f"unknown models subcommand: {subcmd}")
        info("usage: opencode-proxy models {list|best}")
        return

    section("free models")
    try:
        data = json.loads(urllib.request.urlopen(API_URL + "/healthz", timeout=5).read().decode())
        models = data.get("models", {})
        info(f"upstream models: {models.get('total', 0)}, free ones exposed: {models.get('exposed', 0)}")
    except Exception:
        warn("the gateway is not reachable, showing the known models")
        info("start it with: opencode-proxy start")

    if subcmd == "best":
        for rank, (name, meta) in enumerate(sorted(MODEL_INFO.items(), key=lambda kv: kv[1]["rank"]), 1):
            if rank > 3:
                break
            print(f"  {rank}. {name}  {DIM}{meta['ctx']} - {meta['use']}{NC}")
        return

    print()
    print(f"  {DIM}{'model':<35} {'context':<9} best for{NC}")
    for name, meta in sorted(MODEL_INFO.items(), key=lambda kv: kv[1]["rank"]):
        print(f"  {GREEN}{name:<35}{NC} {BLUE}{meta['ctx']:<9}{NC} {meta['use']}")
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
    checks.append(("architecture", ARCH, ARCH in ("aarch64", "arm64")))

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

    if healthy:
        try:
            health = json.loads(urllib.request.urlopen(API_URL + "/healthz", timeout=3).read().decode())
            warp = health.get("warp", {})
            checks.append((
                "warp egress",
                f"{warp.get('status', '?')} (active {warp.get('active', '?')}, standby {warp.get('standby', '?')})",
                warp.get("status") not in ("error", "failed"),
            ))
            models = health.get("models", {})
            checks.append((
                "free models",
                f"{models.get('exposed', '?')} of {models.get('total', '?')} upstream",
                bool(models.get("exposed")),
            ))
        except Exception:
            pass

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
    if not routed:
        info("repoint OpenCode at the proxy: python3 setup.py install")
        info("or inspect the current config: opencode-proxy config")
    if not on_path:
        info("put the commands back on PATH: opencode-proxy repair")
        info(f"or in this shell: export PATH=\"{LOCAL_BIN}:$PATH\"")
    if bundle is None:
        info("install the CA bundle the gateway needs: opencode-proxy fix-certs")


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
    """Fetch the latest setup.py from GitHub."""
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

    for path in (PID_FILE, LOG_FILE, CONFIG_FILE, ENGINE_BIN, OPENCODE_BIN,
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

    ok("uninstall complete")


def do_watchdog():
    """Restart the gateway whenever it stops answering."""
    section("watchdog")
    info("watching the proxy, ctrl+c to stop")
    try:
        while True:
            if not health_ok():
                warn("proxy is down, restarting it")
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
    *)
        echo "usage: opencode-proxy {install|repair|start|stop|restart|status|test [model]|bench [model]|logs|update|uninstall|backup|restore [file]|watchdog|version|validate|models [list|best]|model <name>|config|doctor|continue|fix-dns|fix-certs|zoom-in|zoom-out|zoom-reset|thinking <mode>|rate-limit|autostart {enable|disable|status}}"
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


def do_install():
    if ARCH not in ("aarch64", "arm64"):
        err(f"{ARCH} is not supported, this needs aarch64")
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
    if not step("writing the configuration", write_config):
        failed.append("configuration")
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
    info("nothing was changed")


ACTIONS = [
    "install", "repair", "start", "stop", "restart", "status", "test", "bench",
    "logs", "update", "uninstall", "backup", "restore", "watchdog", "version",
    "validate", "dry-run", "models", "model", "config", "doctor", "continue",
    "fix-dns", "fix-certs", "zoom-in", "zoom-out", "zoom-reset", "thinking",
    "rate-limit", "autostart",
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


if __name__ == "__main__":
    main()
