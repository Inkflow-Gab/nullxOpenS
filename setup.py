#!/usr/bin/env python3
"""OpenCode UNLIMITED — all-in-one setup & controller.

Works on native Termux (pkg) and inside proot-distro Ubuntu (apt).
Auto-detects environment and skips Termux-only packages when not on Termux.
Built and maintained by null.
"""

import os
import sys
import json
import time
import shutil
import subprocess
import urllib.request
import tarfile
import argparse
import socket
import tempfile
from pathlib import Path

# ── Colors ──
RED = "\033[0;31m"
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
MAGENTA = "\033[0;35m"
BOLD = "\033[1m"
NC = "\033[0m"


def cprint(msg, color=NC):
    print(f"{color}{msg}{NC}")


def header(msg):
    cprint(f"\n{BOLD}{CYAN}=== {msg} ==={NC}", CYAN)


def success(msg):
    cprint(f"{BOLD}{GREEN}[✓]{NC} {msg}", GREEN)


def info(msg):
    cprint(f"{BLUE}[→]{NC} {msg}", BLUE)


def warn(msg):
    cprint(f"{YELLOW}[!]{NC} {msg}", YELLOW)


def error(msg):
    cprint(f"{RED}[✗]{NC} {msg}", RED)


def which(cmd):
    return shutil.which(cmd)


def run(cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


# ── Paths ──
HOME = Path.home()
BASE_DIR = HOME / ".opencode-proxy"
BIN_DIR = BASE_DIR / "bin"
LOCAL_BIN = HOME / ".local" / "bin"
CONFIG_DIR = HOME / ".config" / "opencode"
PID_FILE = BASE_DIR / "proxy.pid"
LOG_FILE = BASE_DIR / "proxy.log"
CONFIG_FILE = BASE_DIR / "config.json"
DAEMON_FILE = BASE_DIR / "daemon_spawn.py"
MANAGER_FILE = LOCAL_BIN / "opencode-proxy"
ENGINE_BIN = BIN_DIR / "opencode2api"
OPENCODE_BIN = LOCAL_BIN / "opencode-bin"
OPENCODE_WRAPPER = LOCAL_BIN / "opencode"
OPENCODE_UNLIMITED = LOCAL_BIN / "opencode-unlimited"
OPENCODE_JSONC = CONFIG_DIR / "opencode.jsonc"
BACKUP_DIR = BASE_DIR / "backups"
SKILLS_DIR = BASE_DIR / "skills"
BASHRC = HOME / ".bashrc"

ENGINE_VER = "v1.4.6"
ENGINE_URL = (
    "https://github.com/jasonxu114514/opencode2api/releases/download/"
    f"{ENGINE_VER}/opencode2api_{ENGINE_VER}_linux_arm64.tar.gz"
)
SETUP_URL = "https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py"
API_URL = "http://127.0.0.1:8080"
API_KEY = "local-test-key"
ARCH = os.uname().machine

TERMUX_ONLY = {"termux-tools", "glibc-repo", "glibc-runner"}
REQUIRED_PKGS = ["curl", "jq", "proot", "python"]
GLIBC_PKGS = ["glibc-repo", "glibc-runner"]

CONFIG_JSON = {
    "listen": "127.0.0.1:8080",
    "server_keys": ["local-test-key"],
    "zen_keys": [],
    "go_keys": [],
    "anonymous": True,
    "warp": {
        "enabled": True,
        "pool_size": 4,
        "stack": "ipv6",
        "source_ipv6": ""
    },
    "proxies": ["direct"],
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
        "free_only": True
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
        "dump_request_bodies": False
    },
    "webui": {
        "enabled": True,
        "listen": "127.0.0.1:8081",
        "username": "admin",
        "password": "changeme-changeme",
        "session_ttl_minutes": 720
    }
}

# ── Skills Repo (alirezarezvani/claude-skills) ──
SKILLS_REPO_API = "https://api.github.com/repos/alirezarezvani/claude-skills/git/trees/main?recursive=1"
SKILLS_RAW_BASE = "https://raw.githubusercontent.com/alirezarezvani/claude-skills/main/"


def parse_skill_md(content: str) -> dict:
    """Parse SKILL.md frontmatter + body into a skill dict."""
    skill = {
        "name": "",
        "category": "custom",
        "description": "",
        "system_prompt": "",
        "raw": content,
    }
    # Extract YAML frontmatter
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            fm = content[4:end]
            body = content[end + 5:]
            skill["raw"] = body.strip()
            for line in fm.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key == "name":
                        skill["name"] = val
                    elif key == "description":
                        skill["description"] = val
                    elif key == "license":
                        skill["license"] = val
            # category from metadata or default
            skill["category"] = "claude-skills"
    else:
        skill["raw"] = content.strip()
    return skill


def fetch_all_skills() -> list:
    """Fetch all SKILL.md files from the claude-skills repo via the Git Trees API."""
    try:
        req = urllib.request.Request(
            SKILLS_REPO_API,
            headers={"User-Agent": "nullxOpenS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        error(f"Failed to fetch skills tree from GitHub: {e}")
        return []

    tree = data.get("tree", [])
    skills = []
    for item in tree:
        path = item.get("path", "")
        if item.get("type") == "blob" and path.endswith("SKILL.md"):
            # Derive category from path: engineering/agent-memory/skills/agent-memory/SKILL.md
            parts = path.split("/")
            if len(parts) >= 4:
                category = parts[0]  # e.g. engineering, marketing
                skill_name = parts[-2]  # e.g. agent-memory
            else:
                category = "claude-skills"
                skill_name = Path(path).stem
            skills.append({
                "path": path,
                "name": skill_name,
                "category": category,
                "download_url": f"{SKILLS_RAW_BASE}{path}",
            })
    return skills


def download_skill(skill_info: dict, idx: int = 0, total: int = 0) -> dict | None:
    """Download and parse a single SKILL.md from the repo with progress bar."""
    label = skill_info["name"]
    bar_len = 25
    if total > 0:
        percent = min(idx * 100 / total, 100)
        filled = int(bar_len * percent / 100)
        bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
        print(f"\r  {CYAN}[skills]{NC} {bar} {percent:5.1f}%  downloading {label}", end="", flush=True)
    try:
        with urllib.request.urlopen(skill_info["download_url"], timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        warn(f"Failed to download {skill_info['name']}: {e}")
        return None
    skill = parse_skill_md(content)
    skill["source"] = skill_info["path"]
    skill["category"] = skill_info["category"]
    if not skill["name"]:
        skill["name"] = skill_info["name"]
    return skill


def write_skills(dry_run=False):
    """Download skills from alirezarezvani/claude-skills into SKILLS_DIR."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    if dry_run:
        info("[dry-run] Would download skills from alirezarezvani/claude-skills")
        return

    header("Downloading Skills from claude-skills repo")
    info("Fetching skill tree from GitHub...")
    skills = fetch_all_skills()
    if not skills:
        warn("No skills found or GitHub API unavailable.")
        return

    info(f"Found {len(skills)} skills in repo.")
    count = 0
    for i, skill_info in enumerate(skills, 1):
        skill_file = SKILLS_DIR / f"{skill_info['name']}.json"
        if skill_file.exists():
            continue
        skill = download_skill(skill_info, i, len(skills))
        if not skill or not skill["name"]:
            continue
        skill_file.write_text(json.dumps(skill, indent=2))
        count += 1
    # Clear the progress line and show completion
    print(f"\r  {GREEN}[✓]{NC} Done — installed {count}/{len(skills)} skills to {SKILLS_DIR}      ")
    if count > 0:
        success(f"Installed {count} skills from claude-skills repo.")
    else:
        info("All skills already installed.")


DAEMON_SPAWN = r"""#!/usr/bin/env python3
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
"""

MANAGER_SH = r"""#!/usr/bin/env bash
SETUP="$HOME/.opencode-proxy/setup.py"
case "$1" in
    start)   python3 "$SETUP" start ;;
    stop)    python3 "$SETUP" stop ;;
    restart) python3 "$SETUP" restart ;;
    status)  python3 "$SETUP" status ;;
    test)    python3 "$SETUP" test "${2:-deepseek-v4.1-flash-free}" ;;
    logs)    python3 "$SETUP" logs ;;
    update)  python3 "$SETUP" update ;;
    uninstall) python3 "$SETUP" uninstall ;;
    backup)  python3 "$SETUP" backup ;;
    restore) python3 "$SETUP" restore "${2:-}" ;;
    watchdog) python3 "$SETUP" watchdog ;;
    skills)  python3 "$SETUP" skills "${2:-list}" "${3:-}" ;;
    models)  python3 "$SETUP" models "${2:-list}" ;;
    install) python3 "$SETUP" install ;;
    *) echo "Usage: opencode-proxy {install|start|stop|restart|status|test [model]|logs|update|uninstall|backup|restore [file]|watchdog|skills [list|add|remove|show|install] [name]|models [list|best]}"; exit 1 ;;
esac
"""

OPENCODE_WRAPPER_SH = """#!/usr/bin/env bash
exec grun "$HOME/.local/bin/opencode-bin" "$@"
"""

OPENCODE_JSONC_CONTENT = """{
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
"""


# ── Environment detection ──
def detect_env():
    """Return 'termux' or 'linux'.

    Inside proot-distro ubuntu, pkg is mounted from Termux but installing
    Termux-only packages there fails. Check apt-get first: if it exists,
    we're on Ubuntu/proot-distro (native glibc, apt repos). Only use pkg
    if apt-get isn't available (real Termux).
    """
    for apt_path in ("/usr/bin/apt-get", "/bin/apt-get", "apt-get"):
        if os.path.exists(apt_path) or which(apt_path):
            return "linux"
    if which("pkg"):
        try:
            run(["pkg", "--version"], capture=True, check=True)
            return "termux"
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    return "linux"


def fix_dns():
    """Ensure /etc/resolv.conf has a working nameserver on linux/proot-distro.

    Inside proot-distro ubuntu, /etc/resolv.conf often points to [::1]:53 or
    127.0.0.1:53 which WARP's userspace DNS can't use. We back up the original
    and write a public nameserver so Cloudflare registration works.
    Only runs on linux (Termux uses termux-chroot which handles DNS).
    """
    if detect_env() != "linux":
        return
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        return
    try:
        content = resolv.read_text()
    except Exception:
        return
    # If only localhost nameservers, replace with a public one
    nameservers = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("nameserver"):
            parts = line.split()
            if len(parts) == 2:
                nameservers.append(parts[1])
    bad = {"127.0.0.1", "::1", "0.0.0.0"}
    if nameservers and all(ns in bad for ns in nameservers):
        backup = Path("/etc/resolv.conf.opencode-unlimited.bak")
        if not backup.exists():
            try:
                shutil.copy2(resolv, backup)
            except Exception:
                pass
        try:
            resolv.write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
            info("Fixed /etc/resolv.conf for WARP DNS (1.1.1.1, 8.8.8.8)")
        except Exception as e:
            warn(f"Could not fix /etc/resolv.conf: {e}")


# ── Arch check ──
def check_arch():
    if ARCH not in ("aarch64", "arm64"):
        error(f"Architecture {ARCH} not supported. Requires aarch64/ARM64.")
        sys.exit(1)


# ── Package install ──
def install_packages(dry_run=False):
    env = detect_env()
    needed = [p for p in REQUIRED_PKGS if not which(p)]

    if env == "termux":
        if not which("grun"):
            needed += GLIBC_PKGS
        if "termux-tools" not in needed and not which("termux-chroot"):
            needed.append("termux-tools")
    else:
        needed = [p for p in needed if p not in TERMUX_ONLY]
        if not which("python3") and "python" not in needed:
            needed.append("python3")

    needed = [p for p in needed if not which(p)]

    if not needed:
        info("All dependencies already installed.")
        return

    header("Installing Dependencies")
    info(f"Environment: {env}")
    info(f"Packages: {' '.join(needed)}")

    if dry_run:
        info("[dry-run] Would install packages: " + " ".join(needed))
        return

    if env == "termux":
        try:
            run(["pkg", "update", "-y"])
        except subprocess.CalledProcessError:
            warn("pkg update failed — falling back to apt-get")
            env = "linux"

    if env == "termux":
        critical = [p for p in needed if p not in TERMUX_ONLY]
        optional = [p for p in needed if p in TERMUX_ONLY]
        if critical:
            try:
                run(["pkg", "install", "-y"] + critical)
            except subprocess.CalledProcessError as e:
                error(f"Critical pkg install failed: {e}")
                env = "linux"
        for p in optional:
            try:
                run(["pkg", "install", "-y", p])
            except subprocess.CalledProcessError:
                warn(f"Skipping optional package: {p}")
    if env == "linux":
        try:
            run(["apt-get", "update", "-y"])
        except subprocess.CalledProcessError:
            warn("apt-get update failed — continuing anyway")
        try:
            run(["apt-get", "install", "-y"] + needed)
        except subprocess.CalledProcessError as e:
            error(f"Package install had issues: {e} — continuing anyway")

    success("Dependencies installed.")


# ── Download with live progress ──
def download(url, dest):
    """Live single-line download progress (no spamming)."""
    info(f"Downloading {url}")
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        bar_len = 30
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                percent = min(downloaded * 100 / total, 100)
                filled = int(bar_len * percent / 100)
                bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
                kb = downloaded // 1024
                print(f"\r  {BLUE}[dl]{NC} {bar} {percent:5.1f}% ({kb} KB)", end="", flush=True)
    print()
    success("Download complete.")


# ── Tarball extraction ──
def extract_tar(tar_path, dest_dir):
    with tarfile.open(tar_path, "r:gz") as tar:
        try:
            tar.extractall(dest_dir, filter="data")
        except TypeError:
            tar.extractall(dest_dir)


def find_binary(root_dir, name):
    for root, _dirs, files in os.walk(root_dir):
        for f in files:
            if f == name:
                return Path(root) / f
    return None


# ── Engine install ──
def install_engine(dry_run=False):
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if ENGINE_BIN.exists():
        info("opencode2api already installed — skipping engine download.")
        return

    header("Installing opencode2api Engine")
    info(f"Version: {ENGINE_VER}")

    if dry_run:
        info(f"[dry-run] Would download {ENGINE_URL}")
        return

    tmp = BASE_DIR / "opencode2api.tar.gz"
    download(ENGINE_URL, tmp)
    with tempfile.TemporaryDirectory() as td:
        extract_tar(tmp, td)
        binary = find_binary(td, "opencode2api")
        if not binary:
            error("Failed to find opencode2api binary in tarball")
            tmp.unlink(missing_ok=True)
            return
        shutil.copy2(binary, ENGINE_BIN)
    os.chmod(ENGINE_BIN, 0o755)
    tmp.unlink(missing_ok=True)
    success("Engine installed.")


# ── Daemon spawner ──
def write_daemon_spawner():
    DAEMON_FILE.write_text(DAEMON_SPAWN)
    os.chmod(DAEMON_FILE, 0o755)


# ── Config ──
def write_config():
    CONFIG_FILE.write_text(json.dumps(CONFIG_JSON, indent=2))


# ── Skills ──
def do_skills(subcmd="list", name=""):
    """Manage skills: list, add, remove, show, install."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    if subcmd == "list":
        header("Available Skills")
        skill_files = sorted(SKILLS_DIR.glob("*.json"))
        if not skill_files:
            warn("No skills installed. Run 'opencode-proxy skills install' to download from claude-skills repo.")
            return
        for sf in skill_files:
            try:
                skill = json.loads(sf.read_text())
                desc = skill.get("description", "")
                # Truncate long descriptions
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                print(f"  {GREEN}{skill.get('name', sf.stem)}{NC}  {CYAN}[{skill.get('category', '?')}] {NC}{desc}")
            except Exception:
                print(f"  {YELLOW}{sf.stem}{NC}  (invalid skill file)")
        info(f"\nTotal: {len(skill_files)} skills")
        info(f"Use: opencode-proxy skills show <name>  |  opencode-proxy skills add <name>")

    elif subcmd == "install":
        header("Install Skills from claude-skills repo")
        write_skills()

    elif subcmd == "show":
        if not name:
            error("Usage: opencode-proxy skills show <name>")
            return
        skill_file = SKILLS_DIR / f"{name}.json"
        if not skill_file.exists():
            error(f"Skill '{name}' not found. Run 'opencode-proxy skills list' to see available skills.")
            return
        skill = json.loads(skill_file.read_text())
        header(f"Skill: {skill.get('name', name)}")
        info(f"Category : {skill.get('category', '?')}")
        info(f"Source   : {skill.get('source', 'custom')}")
        info(f"Description: {skill.get('description', '')}")
        print(f"\n{MAGENTA}Skill Content (SKILL.md):{NC}")
        raw = skill.get("raw", "")
        if raw:
            # Print first 2000 chars to avoid flooding
            if len(raw) > 2000:
                print(raw[:2000])
                print(f"\n{YELLOW}... (truncated, full content in {skill_file}){NC}")
            else:
                print(raw)
        else:
            print(skill.get("system_prompt", "(no content)"))
        info(f"\nTo use this skill in OpenCode, add the system prompt to your model configuration.")
        info(f"Skill file: {skill_file}")

    elif subcmd == "add":
        if not name:
            error("Usage: opencode-proxy skills add <name>")
            return
        skill_file = SKILLS_DIR / f"{name}.json"
        if skill_file.exists():
            warn(f"Skill '{name}' already exists.")
            return
        desc = input("Enter skill description: ").strip()
        category = input("Enter skill category (e.g. development, design, utilities): ").strip()
        system_prompt = input("Enter system prompt for this skill: ").strip()
        skill = {
            "name": name,
            "category": category or "custom",
            "description": desc or f"Custom skill: {name}",
            "system_prompt": system_prompt or f"You are an expert in {name}.",
            "raw": system_prompt or f"You are an expert in {name}.",
            "source": "custom",
        }
        skill_file.write_text(json.dumps(skill, indent=2))
        success(f"Skill '{name}' created at {skill_file}")

    elif subcmd == "remove":
        if not name:
            error("Usage: opencode-proxy skills remove <name>")
            return
        skill_file = SKILLS_DIR / f"{name}.json"
        if not skill_file.exists():
            error(f"Skill '{name}' not found.")
            return
        skill_file.unlink()
        success(f"Removed skill '{name}'")

    else:
        error(f"Unknown skills subcommand: {subcmd}")
        info("Usage: opencode-proxy skills {list|install|show|add|remove} [name]")


def do_models(subcmd="list"):
    """Detect and rank free models from the gateway."""
    header("OpenCode Free Models")

    try:
        data = json.loads(urllib.request.urlopen(API_URL + "/healthz", timeout=5).read().decode())
    except Exception as e:
        error(f"Cannot reach proxy at {API_URL}/healthz — is the proxy running? ({e})")
        info("Start it with: opencode-proxy start")
        return

    models = data.get("models", {})
    total = models.get("total", 0)
    exposed = models.get("exposed", 0)

    if subcmd == "list":
        info(f"Total upstream: {total}  |  Exposed free: {exposed}")
        print()
        # Known model info for ranking
        model_info = {
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
        # Sort by rank
        sorted_models = sorted(model_info.items(), key=lambda x: x[1]["rank"])
        print(f"  {BOLD}{'Model':<35} {'Context':<10} {'Best For'}{NC}")
        print(f"  {BOLD}{'-'*35} {'-'*10} {'-'*40}{NC}")
        for mname, minfo in sorted_models:
            mark = " ★" if minfo["rank"] <= 3 else ""
            print(f"  {GREEN}{mname:<35}{NC} {BLUE}{minfo['ctx']:<10}{NC} {minfo['use']}{mark}")
        print(f"\n{CYAN}★ = Top 3 recommended free models{NC}")
        info("Use a model in OpenCode: opencode-unlimited-proxy/<model-id>")

    elif subcmd == "best":
        best = [
            ("deepseek-v4.1-flash-free", "Code, algorithms, refactoring", "128K"),
            ("crouton-alpha-free", "Massive context, multimodal docs", "1M"),
            ("nemotron-3.5-super-vl-free", "Vision-language tasks", "1M"),
        ]
        header("Top 3 Free Models")
        for i, (mname, use, ctx) in enumerate(best, 1):
            print(f"  {BOLD}{i}. {mname}{NC}")
            print(f"     Use: {use}  |  Context: {ctx}")
            print(f"     In OpenCode: opencode-unlimited-proxy/{mname}")
            print()
        info("These are the highest-quality free-tier models detected from OpenCode's catalog.")

    else:
        error(f"Unknown models subcommand: {subcmd}")
        info("Usage: opencode-proxy models {list|best}")


# ── Manager CLI ──
def write_manager():
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    MANAGER_FILE.write_text(MANAGER_SH)
    os.chmod(MANAGER_FILE, 0o755)


# ── Unified launcher ──
UNLIMITED_SH = """#!/usr/bin/env bash
# OpenCode UNLIMITED — unified launcher
# Starts the proxy daemon + OpenCode CLI together as one service.
BASE_DIR="$HOME/.opencode-proxy"
LOCAL_BIN="$HOME/.local/bin"
PROXY="$LOCAL_BIN/opencode-proxy"
CLI="$LOCAL_BIN/opencode"

wait_for_proxy() {
    for i in $(seq 1 15); do
        if curl -s "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

case "$1" in
    start)
        "$PROXY" start
        if wait_for_proxy; then
            exec "$CLI"
        else
            echo "[!] Proxy did not become healthy. Run 'opencode-proxy logs' to check."
            exit 1
        fi
        ;;
    stop)
        "$PROXY" stop
        pkill -f "opencode-bin" 2>/dev/null || true
        ;;
    restart)
        "$PROXY" stop
        pkill -f "opencode-bin" 2>/dev/null || true
        sleep 1
        "$PROXY" start
        if wait_for_proxy; then
            exec "$CLI"
        else
            echo "[!] Proxy did not become healthy. Run 'opencode-proxy logs' to check."
            exit 1
        fi
        ;;
    status)
        "$PROXY" status
        if pgrep -f "opencode-bin" >/dev/null 2>&1; then
            echo "OpenCode CLI: RUNNING"
        else
            echo "OpenCode CLI: STOPPED"
        fi
        ;;
    install)
        python3 "$BASE_DIR/setup.py" install
        ;;
    *)
        echo "Usage: opencode-unlimited {install|start|stop|restart|status}"
        exit 1
        ;;
esac
"""

def write_unlimited_launcher():
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    OPENCODE_UNLIMITED.write_text(UNLIMITED_SH)
    os.chmod(OPENCODE_UNLIMITED, 0o755)


# ── OpenCode CLI ──
def validate_opencode_bin():
    """Return True if opencode-bin exists, is non-empty, and is executable."""
    if not OPENCODE_BIN.exists():
        return False
    if OPENCODE_BIN.stat().st_size == 0:
        return False
    if not os.access(OPENCODE_BIN, os.X_OK):
        return False
    return True


def install_opencode_cli(dry_run=False):
    env = detect_env()
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)

    # Validate grun availability on Termux
    if env == "termux":
        if not which("grun"):
            warn("grun not found — OpenCode CLI won't run on Termux without glibc-runner")
            warn("Install with: pkg install glibc-repo glibc-runner")

    # Always (re)write the wrapper based on current environment detection
    if env == "termux":
        OPENCODE_WRAPPER.write_text(OPENCODE_WRAPPER_SH)
    else:
        OPENCODE_WRAPPER.write_text(f"""#!/usr/bin/env bash
exec "{OPENCODE_BIN}" "$@"
""")
    os.chmod(OPENCODE_WRAPPER, 0o755)

    if validate_opencode_bin():
        info("OpenCode CLI already installed — skipping download.")
        return

    header("Installing OpenCode CLI")
    info("Version: 1.19.5")

    if dry_run:
        info("[dry-run] Would download OpenCode CLI tarball")
        return

    url = "https://registry.npmjs.org/opencode-linux-arm64/-/opencode-linux-arm64-1.19.5.tgz"
    tmp = LOCAL_BIN / "opencode-cli.tgz"
    download(url, tmp)
    with tempfile.TemporaryDirectory() as td:
        extract_tar(tmp, td)
        binary = find_binary(td, "opencode")
        if not binary:
            error("Failed to find opencode binary in tarball")
            tmp.unlink(missing_ok=True)
            return
        shutil.copy2(binary, OPENCODE_BIN)
    os.chmod(OPENCODE_BIN, 0o755)
    tmp.unlink(missing_ok=True)
    success("OpenCode CLI installed.")


# ── OpenCode config ──
def write_opencode_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not OPENCODE_JSONC.exists():
        OPENCODE_JSONC.write_text(OPENCODE_JSONC_CONTENT)


# ── PATH ──
def ensure_path():
    path_str = str(LOCAL_BIN)
    if path_str not in os.environ.get("PATH", ""):
        os.environ["PATH"] = path_str + os.pathsep + os.environ.get("PATH", "")
    line = f'export PATH="{LOCAL_BIN}:$PATH"'
    if BASHRC.exists():
        content = BASHRC.read_text()
        if ".local/bin" not in content:
            with open(BASHRC, "a") as f:
                f.write("\n" + line + "\n")
    else:
        BASHRC.write_text(line + "\n")


# ── PID / health ──
def get_pid():
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        if pid:
            try:
                os.kill(int(pid), 0)
                return int(pid)
            except ProcessLookupError:
                pass
    if which("pgrep"):
        try:
            out = run(["pgrep", "-f", str(ENGINE_BIN)], capture=True)
            if out.stdout.strip():
                pid = int(out.stdout.strip().splitlines()[0])
                PID_FILE.write_text(str(pid))
                return pid
        except subprocess.CalledProcessError:
            pass
    return None


def health_ok():
    try:
        urllib.request.urlopen(API_URL + "/healthz", timeout=2)
        return True
    except Exception:
        return False


# ── Daemon control ──
def start_daemon(dry_run=False):
    env = detect_env()
    pid = get_pid()
    if pid:
        warn(f"Already running (PID: {pid})")
        return

    header("Starting Proxy Daemon")
    if dry_run:
        info("[dry-run] Would start opencode2api daemon")
        return

    # Fix DNS on linux/proot-distro so WARP can reach Cloudflare
    fix_dns()

    info("Starting OpenCode Proxy daemon...")
    pid = os.fork()
    if pid > 0:
        for _ in range(15):
            if health_ok():
                success("Proxy online!")
                info(f"API Endpoint: {API_URL}/v1")
                info(f"Dashboard   : http://127.0.0.1:8081")
                info(f"API Key     : {API_KEY}")
                return
            time.sleep(1)
        error("Proxy failed to start. Check logs with: opencode-proxy logs")
        sys.exit(1)
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    devnull = open(os.devnull, "r")
    os.dup2(devnull.fileno(), sys.stdin.fileno())
    log_fd = open(LOG_FILE, "a")
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())
    if env == "termux":
        cmd = ["termux-chroot", str(ENGINE_BIN), "-config", str(CONFIG_FILE)]
    else:
        cmd = [str(ENGINE_BIN), "-config", str(CONFIG_FILE)]
    try:
        os.execv(cmd[0], cmd)
    except Exception as e:
        sys.stderr.write(f"Failed to exec {cmd}: {e}\n")
        os._exit(1)


def stop_daemon(dry_run=False):
    pid = get_pid()
    if pid:
        header("Stopping Proxy Daemon")
        if dry_run:
            info(f"[dry-run] Would stop PID {pid}")
            return
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        try:
            run(["pkill", "-f", str(ENGINE_BIN)])
        except subprocess.CalledProcessError:
            pass
        PID_FILE.unlink(missing_ok=True)
        success("Proxy stopped.")
    else:
        info("Proxy is not running.")


def restart_daemon(dry_run=False):
    stop_daemon(dry_run=True)
    time.sleep(1)
    start_daemon(dry_run=dry_run)


# ── Status ──
def status_daemon():
    pid = get_pid()
    if pid:
        header("Proxy Status")
        success(f"OpenCode Proxy: RUNNING (PID: {pid})")
        try:
            data = json.loads(urllib.request.urlopen(API_URL + "/healthz", timeout=3).read().decode())
            warp = data.get("warp", {})
            info(f"WARP Status : {warp.get('status', '?')} (active: {warp.get('active', '?')}, standby: {warp.get('standby', '?')})")
            models = data.get("models", {})
            info(f"Free Models : {models.get('exposed', '?')} active ({models.get('total', '?')} total upstream)")
        except Exception:
            warn("API Check: initializing or unreachable")
        info(f"API Base    : {API_URL}/v1")
        info(f"Dashboard   : http://127.0.0.1:8081")
    else:
        header("Proxy Status")
        error("OpenCode Proxy: STOPPED")


# ── Test ──
def test_model(model):
    header(f"Testing Model: {model}")
    info("Sending test prompt...")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say: Test successful."}],
        "stream": True
    }).encode()
    req = urllib.request.Request(API_URL + "/v1/chat/completions",
                                 data=payload,
                                 headers={"Authorization": f"Bearer {API_KEY}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                line = line.decode().strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        print()
                        success("Stream completed.")
                        break
                    try:
                        obj = json.loads(data)
                        content = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            print(content, end="", flush=True)
                    except json.JSONDecodeError:
                        pass
        print()
    except Exception as e:
        error(f"Test failed: {e}")


# ── Logs ──
def show_logs():
    header("Proxy Logs")
    if LOG_FILE.exists():
        print(LOG_FILE.read_text(errors="replace")[-5000:])
    else:
        warn("No log file found.")


# ── Update ──
def do_update():
    header("Updating setup.py")
    try:
        tmp = BASE_DIR / "setup.py.new"
        urllib.request.urlretrieve(SETUP_URL, tmp)
        shutil.copy2(tmp, BASE_DIR / "setup.py")
        shutil.copy2(tmp, Path(__file__).resolve())
        tmp.unlink(missing_ok=True)
        success("setup.py updated. Re-run the installer to apply changes.")
    except Exception as e:
        error(f"Update failed: {e}")


# ── Uninstall ──
def do_uninstall():
    header("Uninstalling OpenCode UNLIMITED")
    stop_daemon()
    for p in [PID_FILE, LOG_FILE, CONFIG_FILE, DAEMON_FILE, ENGINE_BIN,
              OPENCODE_BIN, OPENCODE_WRAPPER, MANAGER_FILE, OPENCODE_JSONC]:
        try:
            if p.exists():
                p.unlink()
                info(f"Removed {p}")
        except Exception as e:
            warn(f"Could not remove {p}: {e}")
    for d in [BIN_DIR, BACKUP_DIR]:
        try:
            if d.exists():
                shutil.rmtree(d)
                info(f"Removed {d}")
        except Exception as e:
            warn(f"Could not remove {d}: {e}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    success("Uninstall complete.")


# ── Backup ──
def do_backup():
    header("Backup")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_DIR / f"opencode-backup-{stamp}.tar.gz"
    items = [CONFIG_FILE, OPENCODE_JSONC, BASE_DIR / "setup.py"]
    with tarfile.open(archive, "w:gz") as tar:
        for item in items:
            if item.exists():
                tar.add(item, arcname=item.name)
    success(f"Backup saved to {archive}")


# ── Restore ──
def do_restore(archive_path=""):
    header("Restore")
    if not archive_path:
        # Find latest backup
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backups = sorted(BACKUP_DIR.glob("*.tar.gz"))
        if not backups:
            error("No backup files found in ~/.opencode-proxy/backups/")
            return
        archive_path = str(backups[-1])
        info(f"Using latest backup: {archive_path}")

    archive = Path(archive_path)
    if not archive.exists():
        error(f"Backup file not found: {archive}")
        return

    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(BASE_DIR)
    success(f"Restored from {archive}")
    info("Run 'opencode-proxy restart' to apply.")


# ── Watchdog ──
def do_watchdog():
    header("Watchdog")
    info("Monitoring proxy... (Ctrl+C to stop)")
    try:
        while True:
            if not health_ok():
                warn("Proxy appears down — attempting restart...")
                stop_daemon(dry_run=True)
                time.sleep(1)
                start_daemon(dry_run=True)
            time.sleep(30)
    except KeyboardInterrupt:
        info("Watchdog stopped.")


# ── Version check ──
def do_version():
    header("Version Info")
    info(f"setup.py: OpenCode UNLIMITED")
    info(f"Engine  : opencode2api {ENGINE_VER}")
    info(f"CLI     : OpenCode CLI 1.19.5")
    info(f"Arch    : {ARCH}")
    info(f"Env     : {detect_env()}")


# ── Config validation ──
def do_validate():
    header("Config Validation")
    ok = True
    if CONFIG_FILE.exists():
        try:
            json.loads(CONFIG_FILE.read_text())
            success(f"config.json: valid")
        except json.JSONDecodeError:
            error(f"config.json: invalid JSON")
            ok = False
    else:
        warn(f"config.json: missing")
        ok = False
    if OPENCODE_JSONC.exists():
        success(f"opencode.jsonc: exists")
    else:
        warn(f"opencode.jsonc: missing")
    if ENGINE_BIN.exists():
        success(f"opencode2api binary: present")
    else:
        warn(f"opencode2api binary: missing")
    if OPENCODE_BIN.exists():
        success(f"OpenCode CLI binary: present")
    else:
        warn(f"OpenCode CLI binary: missing")
    return ok


# ── Dry-run install ──
def do_install_dry_run():
    header("Dry-Run Install")
    check_arch()
    detect_env()
    install_packages(dry_run=True)
    install_engine(dry_run=True)
    install_opencode_cli(dry_run=True)
    info("[dry-run] Would write config, manager, wrapper, PATH")
    success("Dry-run complete — nothing was changed.")


# ── Main install ──
def do_install():
    check_arch()
    header("OpenCode UNLIMITED Setup")
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    setup_py_dest = BASE_DIR / "setup.py"
    if not setup_py_dest.exists():
        try:
            urllib.request.urlretrieve(SETUP_URL, setup_py_dest)
        except Exception:
            pass
    install_packages()
    install_engine()
    write_daemon_spawner()
    write_config()
    write_manager()
    write_unlimited_launcher()
    write_skills()
    install_opencode_cli()
    write_opencode_config()
    ensure_path()
    header("Setup Complete!")
    success("Run 'opencode-unlimited' to start gateway + CLI together.")
    info("Or use 'opencode-proxy start' then 'opencode' separately.")
    info("Manage: 'opencode-unlimited {start|stop|restart|status}'")
    info("Skills:  'opencode-proxy skills {list|install|show|add|remove}'")
    info("Models:  'opencode-proxy models {list|best}'")


# ── CLI ──
def main():
    ap = argparse.ArgumentParser(description="OpenCode UNLIMITED all-in-one setup")
    ap.add_argument("action", nargs="?",
                    choices=["install", "start", "stop", "restart", "status",
                             "test", "logs", "update", "uninstall", "backup",
                             "restore", "watchdog", "version", "validate",
                             "dry-run", "skills", "models"],
                    default="install")
    ap.add_argument("model", nargs="?", default="deepseek-v4.1-flash-free")
    ap.add_argument("archive", nargs="?", default="")
    ap.add_argument("skill_name", nargs="?", default="")
    args = ap.parse_args()
    if args.action == "install":
        do_install()
    elif args.action == "start":
        start_daemon()
    elif args.action == "stop":
        stop_daemon()
    elif args.action == "restart":
        restart_daemon()
    elif args.action == "status":
        status_daemon()
    elif args.action == "test":
        test_model(args.model)
    elif args.action == "logs":
        show_logs()
    elif args.action == "update":
        do_update()
    elif args.action == "uninstall":
        do_uninstall()
    elif args.action == "backup":
        do_backup()
    elif args.action == "restore":
        do_restore(args.archive)
    elif args.action == "watchdog":
        do_watchdog()
    elif args.action == "version":
        do_version()
    elif args.action == "validate":
        do_validate()
    elif args.action == "dry-run":
        do_install_dry_run()
    elif args.action == "skills":
        do_skills(args.model, args.skill_name)
    elif args.action == "models":
        do_models(args.model)


if __name__ == "__main__":
    main()