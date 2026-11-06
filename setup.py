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

# ════════════════════════════════════════════════════════════════════════════
# Colors
# ════════════════════════════════════════════════════════════════════════════
RED = "\033[0;31m"
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
MAGENTA = "\033[0;35m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"


def cprint(msg, color=NC):
    print(f"{color}{msg}{NC}")


def header(msg):
    cprint(f"\n{BOLD}{CYAN}═══ {msg} ═══{NC}", CYAN)


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


# ════════════════════════════════════════════════════════════════════════════
# Paths
# ════════════════════════════════════════════════════════════════════════════
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
REQUIRED_PKGS = ["curl", "jq", "proot", "python", "nodejs"]
GLIBC_PKGS = ["glibc-repo", "glibc-runner"]

# ════════════════════════════════════════════════════════════════════════════
# REA — Reverse Engineer Anything (morluto/rea)
# ════════════════════════════════════════════════════════════════════════════
REA_PKG = "rea-agents"
REA_SETUP_URL = "https://github.com/morluto/rea"

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

# ════════════════════════════════════════════════════════════════════════════
# Skills Repo (alirezarezvani/claude-skills)
# ════════════════════════════════════════════════════════════════════════════
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
            parts = path.split("/")
            if len(parts) >= 4:
                category = parts[0]
                skill_name = parts[-2]
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
    print(f"\r  {GREEN}[✓]{NC} Done — installed {count}/{len(skills)} skills to {SKILLS_DIR}      ")
    if count > 0:
        success(f"Installed {count} skills from claude-skills repo.")
    else:
        info("All skills already installed.")


# ════════════════════════════════════════════════════════════════════════════
# Skills Management
# ════════════════════════════════════════════════════════════════════════════
def do_skills(subcmd="list", name=""):
    """Manage skills: list, add, remove, show, install, sync, search, categories."""
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
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                print(f"  {GREEN}{skill.get('name', sf.stem)}{NC}  {CYAN}[{skill.get('category', '?')}] {NC}{desc}")
            except Exception:
                print(f"  {YELLOW}{sf.stem}{NC}  (invalid skill file)")
        info(f"\nTotal: {len(skill_files)} skills")
        info("Use: opencode-proxy skills show <name>  |  opencode-proxy skills search <term>  |  opencode-proxy skills categories")

    elif subcmd == "install":
        header("Install Skills from claude-skills repo")
        write_skills()

    elif subcmd == "sync":
        header("Sync Skills from claude-skills repo")
        write_skills()

    elif subcmd == "search":
        if not name:
            error("Usage: opencode-proxy skills search <term>")
            return
        header(f"Search Skills: '{name}'")
        skill_files = sorted(SKILLS_DIR.glob("*.json"))
        if not skill_files:
            warn("No skills installed. Run 'opencode-proxy skills install' first.")
            return
        term_lower = name.lower()
        found = False
        for sf in skill_files:
            try:
                skill = json.loads(sf.read_text())
                haystack = f"{skill.get('name','')} {skill.get('category','')} {skill.get('description','')} {skill.get('raw','')}".lower()
                if term_lower in haystack:
                    desc = skill.get("description", "")
                    if len(desc) > 60:
                        desc = desc[:57] + "..."
                    print(f"  {GREEN}{skill.get('name', sf.stem)}{NC}  {CYAN}[{skill.get('category', '?')}] {NC}{desc}")
                    found = True
            except Exception:
                pass
        if not found:
            warn(f"No skills matching '{name}' found.")
        else:
            info(f"\nUse: opencode-proxy skills show <name>")

    elif subcmd == "categories":
        header("Skill Categories")
        skill_files = sorted(SKILLS_DIR.glob("*.json"))
        if not skill_files:
            warn("No skills installed. Run 'opencode-proxy skills install' first.")
            return
        cats = {}
        for sf in skill_files:
            try:
                skill = json.loads(sf.read_text())
                cat = skill.get("category", "uncategorized")
                cats.setdefault(cat, []).append(skill)
            except Exception:
                pass
        for cat, skills_list in sorted(cats.items()):
            print(f"  {MAGENTA}{cat}{NC}  {DIM}({len(skills_list)} skills){NC}")
            for s in skills_list[:5]:
                print(f"    {GREEN}{s.get('name')}{NC}  {DIM}- {s.get('description','')[:50]}{NC}")
            if len(skills_list) > 5:
                print(f"    {DIM}... and {len(skills_list) - 5} more{NC}")
            print()

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
            if len(raw) > 2000:
                print(raw[:2000])
                print(f"\n{YELLOW}... (truncated, full content in {skill_file}){NC}")
            else:
                print(raw)
        else:
            print(skill.get("system_prompt", "(no content)"))
        info(f"\nTo use this skill in OpenCode, add the system prompt to your model configuration.")
        info(f"Skill file: {skill_file}")

    elif subcmd == "apply-skill":
        if not name:
            error("Usage: opencode-proxy apply-skill <name>")
            return
        skill_file = SKILLS_DIR / f"{name}.json"
        if not skill_file.exists():
            error(f"Skill '{name}' not found. Run 'opencode-proxy skills list' to see available skills.")
            return
        skill = json.loads(skill_file.read_text())
        system_prompt = skill.get("raw") or skill.get("system_prompt", "")
        if not system_prompt:
            error(f"Skill '{name}' has no system prompt content.")
            return
        write_opencode_config_with_skill(system_prompt, skill.get("name", name))
        success(f"Skill '{name}' applied to OpenCode config. Restart OpenCode to use it.")

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

    elif subcmd == "export":
        if not name:
            error("Usage: opencode-proxy skills export <file.json>")
            info("Example: opencode-proxy skills export my-skills-backup.json")
            return
        export_path = Path(name)
        if not export_path.suffix:
            export_path = export_path.with_suffix(".json")
        skill_files = sorted(SKILLS_DIR.glob("*.json"))
        if not skill_files:
            warn("No skills installed to export.")
            return
        bundle = {
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "alirezarezvani/claude-skills",
            "total": len(skill_files),
            "skills": [],
        }
        for sf in skill_files:
            try:
                skill = json.loads(sf.read_text())
                bundle["skills"].append(skill)
            except Exception:
                pass
        export_path.write_text(json.dumps(bundle, indent=2))
        success(f"Exported {len(bundle['skills'])} skills to {export_path}")
        info("Use: opencode-proxy skills import <file.json>  (to restore on another device)")

    elif subcmd == "import":
        if not name:
            error("Usage: opencode-proxy skills import <file.json>")
            info("Example: opencode-proxy skills import my-skills-backup.json")
            return
        import_path = Path(name)
        if not import_path.exists():
            error(f"File not found: {import_path}")
            return
        try:
            bundle = json.loads(import_path.read_text())
        except json.JSONDecodeError as e:
            error(f"Invalid JSON: {e}")
            return
        skills_list = bundle.get("skills", [])
        if not skills_list:
            warn("No skills found in bundle.")
            return
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        imported = 0
        skipped = 0
        for skill in skills_list:
            sname = skill.get("name", "")
            if not sname:
                skipped += 1
                continue
            skill_file = SKILLS_DIR / f"{sname}.json"
            if skill_file.exists():
                skipped += 1
                continue
            skill_file.write_text(json.dumps(skill, indent=2))
            imported += 1
        success(f"Imported {imported} skills (skipped {skipped} already installed).")
        info(f"Total skills now: {len(list(SKILLS_DIR.glob('*.json')))}")

    else:
        error(f"Unknown skills subcommand: {subcmd}")
        info("Usage: opencode-proxy skills {list|install|sync|search|categories|show|add|remove|apply-skill|export|import} [name|file]")


def write_opencode_config_with_skill(system_prompt: str, skill_name: str):
    """Write OpenCode config with a skill's system prompt as the default model instructions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    thinking_text = thinking_indicator_plain()
    # Prepend thinking indicator to skill system prompt
    sp_with_thinking = f"{thinking_text}\n\n{system_prompt}".strip()
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "opencode-unlimited-proxy/deepseek-v4.1-flash-free",
        "system_prompt": sp_with_thinking,
        "permission": {
            "*": "allow", "bash": "allow", "read": "allow", "write": "allow",
            "edit": "allow", "glob": "allow", "grep": "allow", "list": "allow", "websearch": "allow"
        },
        "provider": {
            "opencode-unlimited-proxy": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "opencode-unlimited-proxy",
                "options": {"baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local-test-key"},
                "models": {
                    "beam-free": {}, "big-pickle": {}, "crouton-alpha-free": {},
                    "deepseek-v4.1-flash-free": {}, "flint-40b-free": {}, "glm-5.3-flash-free": {},
                    "mimo-v2.6-flash-free": {}, "nemotron-3.5-lightning-free": {},
                    "nemotron-3.5-super-vl-free": {}, "pulse-alpha-free": {}
                }
            }
        }
    }
    OPENCODE_JSONC.write_text(json.dumps(config, indent=2))


# ════════════════════════════════════════════════════════════════════════════
# Model Management
# ════════════════════════════════════════════════════════════════════════════
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
        sorted_models = sorted(MODEL_INFO.items(), key=lambda x: x[1]["rank"])
        print(f"  {BOLD}{'Model':<35} {'Context':<10} {'Best For'}{NC}")
        print(f"  {BOLD}{'-'*35} {'-'*10} {'-'*40}{NC}")
        for mname, minfo in sorted_models:
            mark = " ★" if minfo["rank"] <= 3 else ""
            print(f"  {GREEN}{mname:<35}{NC} {BLUE}{minfo['ctx']:<10}{NC} {minfo['use']}{mark}")
        print(f"\n{CYAN}★ = Top 3 recommended free models{NC}")
        info("Use a model in OpenCode: opencode-unlimited-proxy/<model-id>")
        info("Switch model: opencode-proxy model <model-id>")

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


def do_model(name=""):
    """Switch the default OpenCode model."""
    if not name:
        error("Usage: opencode-proxy model <model-id>")
        info("Available models: " + ", ".join(MODEL_INFO.keys()))
        return

    header(f"Switching Model to: {name}")

    # Read current config
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    current_config = {}
    if OPENCODE_JSONC.exists():
        try:
            current_config = json.loads(OPENCODE_JSONC.read_text())
        except Exception:
            pass

    current_config["model"] = f"opencode-unlimited-proxy/{name}"
    OPENCODE_JSONC.write_text(json.dumps(current_config, indent=2))
    success(f"Default model switched to: {name}")
    info("Restart OpenCode to apply: opencode-unlimited restart")


def do_continue():
    """Resume the previous OpenCode session (opencode --continue)."""
    header("Resuming OpenCode Session")
    if not OPENCODE_WRAPPER.exists():
        error("OpenCode wrapper not found. Run: opencode-proxy install")
        return
    info("Running: opencode --continue")
    try:
        run(["bash", str(OPENCODE_WRAPPER), "--continue"], check=False)
    except KeyboardInterrupt:
        info("Session ended.")


def do_bench(model=""):
    """Benchmark/test a model."""
    if not model:
        error("Usage: opencode-proxy bench <model-id>")
        info("Example: opencode-proxy bench deepseek-v4.1-flash-free")
        return

    header(f"Benchmarking: {model}")
    info("Sending test prompt...")

    payload = json.dumps({
        "model": f"opencode-unlimited-proxy/{model}",
        "messages": [{"role": "user", "content": "Count from 1 to 5 and say hello."}],
        "stream": True
    }).encode()

    start = time.time()
    req = urllib.request.Request(API_URL + "/v1/chat/completions",
                                 data=payload,
                                 headers={"Authorization": f"Bearer {API_KEY}",
                                          "Content-Type": "application/json"})
    try:
        first_token_time = None
        with urllib.request.urlopen(req) as resp:
            for line in resp:
                line = line.decode().strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        content = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content and first_token_time is None:
                            first_token_time = time.time() - start
                        if content:
                            print(content, end="", flush=True)
                    except json.JSONDecodeError:
                        pass
        total_time = time.time() - start
        print()
        success(f"Benchmark complete!")
        info(f"Total time: {total_time:.2f}s")
        if first_token_time:
            info(f"First token: {first_token_time:.2f}s")
    except Exception as e:
        error(f"Benchmark failed: {e}")


# ════════════════════════════════════════════════════════════════════════════
# Config
# ════════════════════════════════════════════════════════════════════════════
def do_config():
    """Show current configuration."""
    header("OpenCode Configuration")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if OPENCODE_JSONC.exists():
        info(f"Config file: {OPENCODE_JSONC}")
        print()
        print(OPENCODE_JSONC.read_text())
    else:
        warn("opencode.jsonc not found.")

    if CONFIG_FILE.exists():
        info(f"\nGateway config: {CONFIG_FILE}")
    else:
        warn("Gateway config.json not found.")


# ════════════════════════════════════════════════════════════════════════════
# Doctor / Diagnostics
# ════════════════════════════════════════════════════════════════════════════
def do_doctor():
    """Run diagnostics on the setup."""
    header("Doctor — System Diagnostics")
    checks = []

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python", py_ver, True))

    # Architecture
    checks.append(("Architecture", ARCH, ARCH in ("aarch64", "arm64")))

    # Environment
    env = detect_env()
    checks.append(("Environment", env, True))

    # Dependencies
    for pkg in REQUIRED_PKGS:
        present = which(pkg) is not None
        checks.append((f"Package: {pkg}", "installed" if present else "missing", present))

    if env == "termux":
        for pkg in GLIBC_PKGS:
            present = which(pkg) is not None
            checks.append((f"Package: {pkg}", "installed" if present else "missing", present))

    # Binaries
    checks.append(("opencode2api binary", "present" if ENGINE_BIN.exists() else "missing", ENGINE_BIN.exists()))
    checks.append(("OpenCode CLI binary", "present" if OPENCODE_BIN.exists() else "missing", OPENCODE_BIN.exists()))
    checks.append(("opencode wrapper", "present" if OPENCODE_WRAPPER.exists() else "missing", OPENCODE_WRAPPER.exists()))

    # Configs
    checks.append(("gateway config", "present" if CONFIG_FILE.exists() else "missing", CONFIG_FILE.exists()))
    oc_jsonc_ok = OPENCODE_JSONC.exists()
    if oc_jsonc_ok:
        try:
            cfg = json.loads(OPENCODE_JSONC.read_text())
            opts = cfg.get("provider", {}).get("opencode-unlimited-proxy", {}).get("options", {})
            oc_jsonc_ok = opts.get("baseURL", "") == "http://127.0.0.1:8080/v1"
        except Exception:
            oc_jsonc_ok = False
    checks.append(("opencode.jsonc → proxy", "routed" if oc_jsonc_ok else "not routed", oc_jsonc_ok))

    # Skills
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skill_count = len(list(SKILLS_DIR.glob("*.json")))
    checks.append(("installed skills", f"{skill_count} files", skill_count > 0))

    # Gateway health
    gw_healthy = health_ok()
    checks.append(("gateway health", "online" if gw_healthy else "offline", gw_healthy))

    # Thinking mode indicator
    thinking_mode, thinking_enabled = get_thinking_mode()
    checks.append(("thinking mode", thinking_indicator(), thinking_enabled or thinking_mode != "none"))

    # Print results
    all_ok = True
    for name, status, ok in checks:
        icon = "✓" if ok else "✗"
        color = GREEN if ok else RED
        cprint(f"  {icon} {name}: {color}{status}{NC}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        success("All checks passed!")
    else:
        warn("Some checks failed. Review the items marked ✗ above.")

    # Suggestions
    print(f"\n{CYAN}Suggestions:{NC}")
    if not ENGINE_BIN.exists():
        info("Run: python3 setup.py install  (to install opencode2api engine)")
    if not OPENCODE_BIN.exists():
        info("Run: python3 setup.py install  (to install OpenCode CLI)")
    if not gw_healthy:
        info("Run: opencode-proxy start  (to start the gateway)")
        info("   Then: opencode-proxy fix-dns  (if DNS/WARP is blocked)")
    if not oc_jsonc_ok:
        info("Run: python3 setup.py install  (re-writes opencode.jsonc to route through proxy)")
        info("   Or: opencode-proxy config  (to inspect current config)")
    if skill_count == 0:
        info("Run: opencode-proxy skills install  (to download skills)")


# ════════════════════════════════════════════════════════════════════════════
# Sync skills
# ════════════════════════════════════════════════════════════════════════════
def do_sync():
    """Re-sync skills from claude-skills repo."""
    header("Syncing Skills from claude-skills repo")
    write_skills()


# ════════════════════════════════════════════════════════════════════════════
# Daemon spawner
# ════════════════════════════════════════════════════════════════════════════
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
    bench)   python3 "$SETUP" bench "${2:-deepseek-v4.1-flash-free}" ;;
    logs)    python3 "$SETUP" logs ;;
    update)  python3 "$SETUP" update ;;
    uninstall) python3 "$SETUP" uninstall ;;
    backup)  python3 "$SETUP" backup ;;
    restore) python3 "$SETUP" restore "${2:-}" ;;
    watchdog) python3 "$SETUP" watchdog ;;
    skills)  python3 "$SETUP" skills "${2:-list}" "${3:-}" ;;
    models)  python3 "$SETUP" models "${2:-list}" ;;
    model)   python3 "$SETUP" model "${2:-}" ;;
    config)  python3 "$SETUP" config ;;
    doctor)  python3 "$SETUP" doctor ;;
    sync)    python3 "$SETUP" sync ;;
    apply-skill) python3 "$SETUP" skills apply-skill "${2:-}" ;;
    continue) python3 "$SETUP" continue ;;
    fix-dns) python3 "$SETUP" fix-dns ;;
    zoom-in) python3 "$SETUP" zoom-in ;;
    zoom-out) python3 "$SETUP" zoom-out ;;
    zoom-reset) python3 "$SETUP" zoom-reset ;;
    thinking) python3 "$SETUP" thinking "${2:-}" ;;
    rea) python3 "$SETUP" rea "${2:-}" "${3:-}" ;;
    rate-limit) python3 "$SETUP" rate-limit ;;
    autostart) python3 "$SETUP" autostart "${2:-}" ;;
    install) python3 "$SETUP" install ;;
    *) echo "Usage: opencode-proxy {install|start|stop|restart|status|test [model]|bench [model]|logs|update|uninstall|backup|restore [file]|watchdog|skills [list|install|sync|search|categories|show|add|remove|apply-skill|export|import] [name|file]|models [list|best]|model <name>|config|doctor|sync|apply-skill <name>|continue|fix-dns|zoom-in|zoom-out|zoom-reset|thinking <mode>|rea {setup|analyze|update|help|status|connect} [path]|rate-limit|autostart {enable|disable|status}}"; exit 1 ;;
esac
"""

OPENCODE_WRAPPER_SH = """#!/usr/bin/env bash
# OpenCode CLI wrapper — passes all flags through to opencode-bin.
# Supports: opencode --continue  (resume previous session)
# Shows thinking indicator banner before launching OpenCode CLI.
THINKING_MODE="$(python3 "$HOME/.opencode-proxy/setup.py" thinking status 2>/dev/null | grep -oP '(thinking:\\s*.*)' | head -1 || echo '○ thinking: off')"
echo ""
echo "═════════════════════════════════════════════════════════════════════"
echo "  OpenCode UNLIMITED"
echo "  $THINKING_MODE"
echo "  API: http://127.0.0.1:8080/v1  |  Proxy: opencode2api + WARP"
echo "═════════════════════════════════════════════════════════════════════"
echo ""
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


# ════════════════════════════════════════════════════════════════════════════
# Environment detection
# ════════════════════════════════════════════════════════════════════════════
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


def do_fix_dns():
    """Force-fix /etc/resolv.conf for WARP DNS on any environment."""
    header("Fix DNS for WARP")
    resolv = Path("/etc/resolv.conf")
    if not resolv.exists():
        warn("/etc/resolv.conf not found — nothing to fix")
        return
    try:
        content = resolv.read_text()
    except Exception as e:
        error(f"Cannot read /etc/resolv.conf: {e}")
        return
    backup = Path("/etc/resolv.conf.opencode-unlimited.bak")
    if not backup.exists():
        try:
            shutil.copy2(resolv, backup)
            info(f"Backed up original to {backup}")
        except Exception:
            pass
    try:
        resolv.write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
        success("/etc/resolv.conf set to 1.1.1.1, 8.8.8.8")
        info("Run 'opencode-proxy restart' to apply.")
    except Exception as e:
        error(f"Could not write /etc/resolv.conf: {e}")


def get_thinking_mode():
    """Read current thinking mode from opencode.jsonc."""
    if not OPENCODE_JSONC.exists():
        return "none", False
    try:
        cfg = json.loads(OPENCODE_JSONC.read_text())
        thinking = cfg.get("thinking", {})
        mode = thinking.get("mode", "none")
        enabled = thinking.get("enabled", mode != "none")
        return mode, enabled
    except Exception:
        return "none", False


def thinking_indicator():
    """Return a visual indicator string for current thinking mode."""
    mode, enabled = get_thinking_mode()
    if not enabled or mode == "none":
        return f"{DIM}○ thinking: off{NC}"
    if mode == "max":
        return f"{BOLD}{MAGENTA}● thinking: MAX{NC}"
    if mode == "high":
        return f"{BOLD}{RED}▲ thinking: high{NC}"
    if mode == "medium":
        return f"{BOLD}{YELLOW}▲ thinking: medium{NC}"
    if mode == "low":
        return f"{BOLD}{BLUE}▲ thinking: low{NC}"
    return f"{DIM}○ thinking: {mode}{NC}"


def thinking_indicator_plain():
    """Return a plain-text thinking indicator (no color codes) for CLI display."""
    mode, enabled = get_thinking_mode()
    if not enabled or mode == "none":
        return "○ thinking: off"
    if mode == "max":
        return "● thinking: MAX"
    if mode == "high":
        return "▲ thinking: high"
    if mode == "medium":
        return "▲ thinking: medium"
    if mode == "low":
        return "▲ thinking: low"
    return f"○ thinking: {mode}"


def do_thinking(mode=""):
    """Set model thinking/reasoning mode or show status.

    Writes the thinking config into opencode.jsonc so DeepSeek and other
    models use the specified reasoning effort.
    Usage: opencode-proxy thinking <mode>  (low, medium, max, high, none)
           opencode-proxy thinking status  (show current mode with indicator)
    """
    if not mode:
        error("Usage: opencode-proxy thinking <mode>")
        info("Modes: low, medium, max (DeepThink max for DeepSeek), high, none")
        info("Example: opencode-proxy thinking max")
        info("         opencode-proxy thinking status")
        return

    mode_lower = mode.lower()

    # Handle status subcommand
    if mode_lower == "status":
        current_mode, enabled = get_thinking_mode()
        header("Thinking Mode Status")
        print(f"\n  {thinking_indicator()}\n")
        if not enabled or current_mode == "none":
            info("Thinking is currently disabled.")
            info("Enable it with: opencode-proxy thinking max")
        else:
            info(f"Current thinking mode: {BOLD}{current_mode}{NC}")
            if current_mode == "max":
                info("DeepThink/max thinking is active for DeepSeek models.")
            info("Restart OpenCode to apply changes: opencode-unlimited restart")
        return

    valid_modes = {"low", "medium", "max", "high", "none"}
    if mode_lower not in valid_modes:
        error(f"Invalid thinking mode: {mode}")
        info("Valid modes: low, medium, max, high, none")
        return

    header(f"Setting Thinking Mode: {mode_lower}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Read current config
    current_config = {}
    if OPENCODE_JSONC.exists():
        try:
            current_config = json.loads(OPENCODE_JSONC.read_text())
        except Exception:
            pass

    # Set thinking config at top level
    current_config["thinking"] = {
        "mode": mode_lower,
        "enabled": mode_lower != "none",
    }

    # Also add thinking to the deepseek model options if present
    provider = current_config.setdefault("provider", {})
    opencode_provider = provider.setdefault("opencode-unlimited-proxy", {})
    models = opencode_provider.setdefault("models", {})
    if "deepseek-v4.1-flash-free" in models:
        models["deepseek-v4.1-flash-free"]["thinking"] = {
            "mode": mode_lower,
            "enabled": mode_lower != "none",
        }

    OPENCODE_JSONC.write_text(json.dumps(current_config, indent=2))
    success(f"Thinking mode set to: {mode_lower}")
    if mode_lower == "max":
        info("DeepThink/max thinking enabled for DeepSeek models.")
    info("Restart OpenCode to apply: opencode-unlimited restart")
    info(f"Current status: {thinking_indicator()}")


def do_rea(subcmd="status", arg=""):
    """Manage REA — Reverse Engineer Anything (morluto/rea).

    Subcommands:
      status   Show rea installation status
      setup    Run `rea setup` to configure your agent (interactive)
      analyze  Run `rea analyze-javascript-application <path> --json`
      update   Run `rea update`
      help     Show `rea --help`
    """
    if not which("rea"):
        warn("rea not installed. Run: opencode-proxy install  (installs rea-agents globally)")
        info("Or install manually: npm install --global rea-agents")
        return

    if subcmd == "status":
        header("REA — Reverse Engineer Anything")
        try:
            out = run(["rea", "--version"], capture=True)
            info(f"rea version: {out.stdout.strip()}")
        except Exception:
            info("rea version: unknown")
        info(f"rea binary: {which('rea')}")
        info("")
        info("Usage:")
        info("  opencode-proxy rea setup          # configure your agent (interactive)")
        info("  opencode-proxy rea analyze <path> # analyze a JS/Electron app dir")
        info("  opencode-proxy rea update         # update rea-agents")
        info("  opencode-proxy rea help           # show rea --help")
        return

    if subcmd == "setup":
        header("REA Setup — Configure Your Agent")
        info("Running: rea setup  (interactive — approve changes when prompted)")
        run(["rea", "setup"], check=False)
        return

    if subcmd == "analyze":
        if not arg:
            error("Usage: opencode-proxy rea analyze <path>")
            info("Example: opencode-proxy rea analyze /path/to/electron-app")
            info("         opencode-proxy rea analyze /path/to/extracted-asar")
            return
        header(f"REA Analyze: {arg}")
        info("Running: rea analyze-javascript-application <path> --json")
        run(["rea", "analyze-javascript-application", arg, "--json"], check=False)
        return

    if subcmd == "update":
        header("REA Update")
        info("Running: rea update")
        run(["rea", "update"], check=False)
        return

    if subcmd == "help":
        header("REA Help")
        run(["rea", "--help"], check=False)
        return

    if subcmd == "connect":
        do_rea_connect()
        return

    error(f"Unknown rea subcommand: {subcmd}")
    info("Usage: opencode-proxy rea {setup|analyze|update|help|status|connect} [path]")


def do_rea_connect():
    """Connect REA to OpenCode Unlimited proxy as its LLM backend.

    Sets OPENAI_BASE_URL and OPENAI_API_KEY so rea routes its LLM calls
    through opencode2api (http://127.0.0.1:8080/v1) with WARP IP rotation.
    Creates a wrapper script at ~/.local/bin/rea-unlimited that launches
    rea with the correct environment.
    """
    header("REA — Connect to OpenCode Unlimited")

    # Check proxy is running
    if not health_ok():
        error("Proxy is not running. Start it first: opencode-proxy start")
        return

    # Verify rea is installed
    if not which("rea"):
        warn("rea not installed. Installing now...")
        run(["npm", "install", "--global", REA_PKG], check=False)
        if not which("rea"):
            error("Failed to install rea-agents.")
            return

    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    rea_unlimited = LOCAL_BIN / "rea-unlimited"

    # Create wrapper script that sets OpenAI-compatible env vars pointing
    # to the local OpenCode proxy (with WARP rotation).
    wrapper = f"""#!/usr/bin/env bash
# rea-unlimited — REA connected to OpenCode Unlimited proxy
# Routes REA's LLM calls through opencode2api (WARP IPv6 rotation).
export OPENAI_BASE_URL="http://127.0.0.1:8080/v1"
export OPENAI_API_KEY="local-test-key"
export OPENAI_MODEL="deepseek-v4.1-flash-free"
export REA_MODEL="deepseek-v4.1-flash-free"

exec rea "$@"
"""
    rea_unlimited.write_text(wrapper)
    os.chmod(rea_unlimited, 0o755)

    success("REA connected to OpenCode Unlimited proxy!")
    info(f"Wrapper created: {rea_unlimited}")
    info("")
    info("Usage:")
    info(f"  {rea_unlimited} --help                          # show REA help")
    info(f"  {rea_unlimited} analyze-javascript-application <path>  --json")
    info("")
    info("Environment variables set:")
    info("  OPENAI_BASE_URL  = http://127.0.0.1:8080/v1  (OpenCode proxy)")
    info("  OPENAI_API_KEY   = local-test-key")
    info("  OPENAI_MODEL     = deepseek-v4.1-flash-free")
    info("  REA_MODEL        = deepseek-v4.1-flash-free")
    info("")
    info("REA's LLM calls now route through opencode2api with WARP IP rotation.")
    info("Make sure the proxy is running: opencode-proxy start")


def do_rate_limit():
    """Scan proxy logs for rate-limit / 429 events and show stats."""
    header("Rate-Limit Monitor")
    if not LOG_FILE.exists():
        warn(f"No log file at {LOG_FILE}")
        info("Start the proxy first: opencode-proxy start")
        return
    try:
        lines = LOG_FILE.read_text(errors="replace").splitlines()
    except Exception as e:
        error(f"Cannot read log file: {e}")
        return
    total = len(lines)
    rate_limited = []
    models_affected = {}
    for line in lines:
        low = line.lower()
        if "429" in low or "rate limit" in low or "usage exceeded" in low or "quota" in low:
            rate_limited.append(line)
            # try to extract a model name
            for mname in MODEL_INFO:
                if mname in line:
                    models_affected[mname] = models_affected.get(mname, 0) + 1
                    break
    info(f"Total log lines scanned: {total}")
    info(f"Rate-limit / 429 events: {len(rate_limited)}")
    if rate_limited:
        print(f"\n  {RED}Recent events:{NC}")
        for line in rate_limited[-5:]:
            print(f"    {DIM}{line[:120]}{NC}")
        if models_affected:
            print(f"\n  {CYAN}Models affected:{NC}")
            for mname, count in sorted(models_affected.items(), key=lambda x: -x[1]):
                print(f"    {GREEN}{mname}{NC}: {count} events")
        print(f"\n  {YELLOW}Suggestions:{NC}")
        info("  - Run: opencode-proxy fix-dns  (if DNS/WARP is blocked)")
        info("  - Switch model: opencode-proxy model <another-free-model>")
        info("  - Restart proxy: opencode-proxy restart")
    else:
        success("No rate-limit events found in logs.")


def do_autostart(action=""):
    """Configure auto-start of the proxy on device boot (Termux termux-boot)."""
    header("Auto-Start on Boot")
    termux_boot = Path.home() / ".termux" / "boot"
    start_script = termux_boot / "opencode-proxy-start.sh"

    if not action:
        error("Usage: opencode-proxy autostart {enable|disable|status}")
        info("")
        if start_script.exists():
            info("Status: ENABLED — proxy starts on boot")
            print(f"  Script: {start_script}")
        else:
            info("Status: DISABLED — proxy does not start on boot")
        info("")
        info("Enable:  opencode-proxy autostart enable")
        info("Disable: opencode-proxy autostart disable")
        return

    action = action.lower()
    if action == "status":
        if start_script.exists():
            success("Auto-start: ENABLED")
            print(f"  Script: {start_script}")
        else:
            info("Auto-start: DISABLED")
        return

    if action == "enable":
        termux_boot.mkdir(parents=True, exist_ok=True)
        script_content = f"""#!/data/data/com.termux/files/usr/bin/bash
# Auto-start OpenCode UNLIMITED proxy on boot
sleep 10
{HOME}/.local/bin/opencode-proxy start >/dev/null 2>&1 &
{HOME}/.local/bin/opencode-unlimited start --continue >/dev/null 2>&1 &
"""
        start_script.write_text(script_content)
        os.chmod(start_script, 0o755)
        success("Auto-start ENABLED — proxy will start on device boot")
        info("Script: " + str(start_script))
        info("Note: Requires Termux with termux-boot app installed.")
        return

    if action == "disable":
        if start_script.exists():
            start_script.unlink()
            success("Auto-start DISABLED")
        else:
            info("Auto-start was already disabled.")
        return

    error(f"Unknown autostart action: {action}")
    info("Usage: opencode-proxy autostart {enable|disable|status}")


def do_zoom_in():
    """Increase terminal font size (Termux)."""
    header("Zoom In — Terminal Font")
    termux_dir = Path.home() / ".termux"
    termux_dir.mkdir(parents=True, exist_ok=True)
    props_file = termux_dir / "termux.properties"

    current_size = 14
    if props_file.exists():
        try:
            for line in props_file.read_text().splitlines():
                if line.strip().startswith("font-size"):
                    parts = line.split("=")
                    if len(parts) == 2:
                        current_size = float(parts[1].strip())
        except Exception:
            pass

    new_size = min(current_size + 2, 32)
    props_file.write_text(f"font-size = {new_size}\n")
    try:
        run(["termux-reload-settings"], check=False)
    except Exception:
        pass
    success(f"Terminal font size: {current_size} -> {new_size}")
    info("Pinch-to-zoom also works in Termux.")


def do_zoom_out():
    """Decrease terminal font size (Termux)."""
    header("Zoom Out — Terminal Font")
    termux_dir = Path.home() / ".termux"
    termux_dir.mkdir(parents=True, exist_ok=True)
    props_file = termux_dir / "termux.properties"

    current_size = 14
    if props_file.exists():
        try:
            for line in props_file.read_text().splitlines():
                if line.strip().startswith("font-size"):
                    parts = line.split("=")
                    if len(parts) == 2:
                        current_size = float(parts[1].strip())
        except Exception:
            pass

    new_size = max(current_size - 2, 8)
    props_file.write_text(f"font-size = {new_size}\n")
    try:
        run(["termux-reload-settings"], check=False)
    except Exception:
        pass
    success(f"Terminal font size: {current_size} -> {new_size}")
    info("Pinch-to-zoom also works in Termux.")


def do_zoom_reset():
    """Reset terminal font size to default (Termux)."""
    header("Zoom Reset — Terminal Font")
    termux_dir = Path.home() / ".termux"
    termux_dir.mkdir(parents=True, exist_ok=True)
    props_file = termux_dir / "termux.properties"

    props_file.write_text("font-size = 14\n")
    try:
        run(["termux-reload-settings"], check=False)
    except Exception:
        pass
    success("Terminal font size reset to 14")


def check_arch():
    if ARCH not in ("aarch64", "arm64"):
        error(f"Architecture {ARCH} not supported. Requires aarch64/ARM64.")
        sys.exit(1)


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
        if not which("npm") and "npm" not in needed:
            needed.append("npm")

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


def install_rea(dry_run=False):
    """Install REA — Reverse Engineer Anything (morluto/rea) globally via npm.

    Provides the `rea` CLI for analyzing binaries, Electron/JS apps, .NET,
    and websites locally with agent tooling.
    """
    header("Installing REA — Reverse Engineer Anything")
    info(f"Package: {REA_PKG} (npm global)")
    info(f"Repo: {REA_SETUP_URL}")

    if dry_run:
        info(f"[dry-run] Would run: npm install --global {REA_PKG}")
        return

    if which("rea"):
        info("rea already installed — skipping.")
        return

    try:
        run(["npm", "install", "--global", REA_PKG])
    except subprocess.CalledProcessError as e:
        error(f"rea-agents install failed: {e}")
        info("Try manually: npm install --global rea-agents")
        return

    if which("rea"):
        success("rea installed globally.")
        info("Run: opencode-proxy rea setup  (configure your agent)")
    else:
        warn("rea installed but binary not on PATH — try: npm bin -g")


def write_daemon_spawner():
    DAEMON_FILE.write_text(DAEMON_SPAWN)
    os.chmod(DAEMON_FILE, 0o755)


def write_config():
    CONFIG_FILE.write_text(json.dumps(CONFIG_JSON, indent=2))


def write_manager():
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    MANAGER_FILE.write_text(MANAGER_SH)
    os.chmod(MANAGER_FILE, 0o755)


# ── Unified launcher ──
UNLIMITED_SH = """#!/usr/bin/env bash
# OpenCode UNLIMITED — interactive menu launcher
# Starts the proxy daemon + OpenCode CLI together as one service.
# Run with no args for the interactive menu; command-line flags still work.
BASE_DIR="$HOME/.opencode-proxy"
LOCAL_BIN="$HOME/.local/bin"
PROXY="$LOCAL_BIN/opencode-proxy"
CLI="$LOCAL_BIN/opencode"
SETUP="$BASE_DIR/setup.py"

wait_for_proxy() {
    for i in $(seq 1 15); do
        if curl -s "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

start_opencode() {
    local cont="$1"
    # Start proxy only if it's not already healthy
    if ! curl -s "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
        "$PROXY" start
        if ! wait_for_proxy; then
            echo "[!] Proxy did not become healthy. Run 'opencode-proxy logs' to check."
            return 1
        fi
    fi
    # Show thinking indicator banner before launching OpenCode CLI
    THINKING_MODE="$(python3 "$BASE_DIR/setup.py" thinking status 2>/dev/null | grep -oP '(thinking:\\s*.*)' | head -1 || echo '○ thinking: off')"
    echo ""
    echo "═════════════════════════════════════════════════════════════════════"
    echo "  OpenCode UNLIMITED"
    echo "  $THINKING_MODE"
    echo "  API: http://127.0.0.1:8080/v1  |  Proxy: opencode2api + WARP"
    echo "═════════════════════════════════════════════════════════════════════"
    echo ""
    if [ "$cont" = "--continue" ]; then
        exec "$CLI" --continue
    else
        exec "$CLI"
    fi
}

show_main_menu() {
    clear
    echo ""
    echo "╔═════════════════════════════════════════════════════════════════════╗"
    echo "║              OpenCode UNLIMITED — Main Menu                        ║"
    echo "╚═════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  1) REA — Reverse Engineer Anything"
    echo "  2) OpenCode Unlimited — Start / Continue"
    echo "  3) Doctor — System Diagnostics"
    echo "  4) Rate-Limit Monitor — Check 429 / usage-exceeded events"
    echo "  5) Model Thinking — Set reasoning mode (low/medium/max)"
    echo "  6) Skills Management — list / search / export / import"
    echo "  7) Model Management — list / switch / bench"
    echo "  8) Terminal Zoom — in / out / reset"
    echo "  9) Fix DNS — WARP DNS fix (1.1.1.1, 8.8.8.8)"
    echo " 10) Auto-Start — enable / disable / status"
    echo "  0) Exit"
    echo ""
    printf "  Select an option: "
}

show_rea_menu() {
    clear
    echo ""
    echo "╔═════════════════════════════════════════════════════════════════════╗"
    echo "║              REA — Reverse Engineer Anything                       ║"
    echo "╚═════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  1) Status — check rea installation + version"
    echo "  2) Setup — configure your agent (interactive)"
    echo "  3) Connect to OpenCode Proxy — route REA through opencode2api + WARP"
    echo "  4) Analyze JavaScript Application — path to app dir / ASAR"
    echo "  5) Update — update rea-agents to latest"
    echo "  6) Help — show rea --help"
    echo "  0) Back to main menu"
    echo ""
    printf "  Select an option: "
}

handle_rea() {
    while true; do
        show_rea_menu
        read -r rea_choice
        case "$rea_choice" in
            1) "$PROXY" rea status ; read -r -p "  Press Enter to continue..." _ ;;
            2) "$PROXY" rea setup ; read -r -p "  Press Enter to continue..." _ ;;
            3) "$PROXY" rea connect ; read -r -p "  Press Enter to continue..." _ ;;
            4) read -r -p "  Enter path to JS/Electron app dir: " rea_path
               if [ -n "$rea_path" ]; then
                   "$PROXY" rea analyze "$rea_path"
               fi
               read -r -p "  Press Enter to continue..." _ ;;
            5) "$PROXY" rea update ; read -r -p "  Press Enter to continue..." _ ;;
            6) "$PROXY" rea help ; read -r -p "  Press Enter to continue..." _ ;;
            0) break ;;
            *) echo "  Invalid option." ; sleep 1 ;;
        esac
    done
}

handle_opencode_unlimited() {
    while true; do
        clear
        echo ""
        echo "╔═════════════════════════════════════════════════════════════════════╗"
        echo "║              OpenCode Unlimited — Start / Continue                 ║"
        echo "╚═════════════════════════════════════════════════════════════════════╝"
        echo ""
        echo "  1) Start (normal)"
        echo "  2) Start --continue (resume previous session)"
        echo "  3) Stop proxy + CLI"
        echo "  4) Restart proxy + CLI"
        echo "  5) Status"
        echo "  0) Back to main menu"
        echo ""
        printf "  Select an option: "
        read -r oc_choice
        case "$oc_choice" in
            1) start_opencode "" ; break ;;
            2) start_opencode "--continue" ; break ;;
            3) "$PROXY" stop ; pkill -f "opencode-bin" 2>/dev/null || true ; read -r -p "  Press Enter to continue..." _ ;;
            4) "$PROXY" stop ; pkill -f "opencode-bin" 2>/dev/null || true ; sleep 1
               "$PROXY" start
               if wait_for_proxy; then
                   THINKING_MODE="$(python3 "$BASE_DIR/setup.py" thinking status 2>/dev/null | grep -oP '(thinking:\\s*.*)' | head -1 || echo '○ thinking: off')"
                   echo ""
                   echo "═════════════════════════════════════════════════════════════════════"
                   echo "  OpenCode UNLIMITED (restarted)"
                   echo "  $THINKING_MODE"
                   echo "  API: http://127.0.0.1:8080/v1  |  Proxy: opencode2api + WARP"
                   echo "═════════════════════════════════════════════════════════════════════"
                   echo ""
                   exec "$CLI"
               else
                   echo "[!] Proxy did not become healthy. Run 'opencode-proxy logs' to check."
                   read -r -p "  Press Enter to continue..." _
               fi
               ;;
            5) "$PROXY" status ; read -r -p "  Press Enter to continue..." _ ;;
            0) break ;;
            *) echo "  Invalid option." ; sleep 1 ;;
        esac
    done
}

# ── Command-line mode (backward compatibility) ──
if [ $# -gt 0 ]; then
    case "$1" in
        start)
            if ! curl -s "http://127.0.0.1:8080/healthz" >/dev/null 2>&1; then
                "$PROXY" start
                if ! wait_for_proxy; then
                    echo "[!] Proxy did not become healthy. Run 'opencode-proxy logs' to check."
                    exit 1
                fi
            fi
            THINKING_MODE="$(python3 "$BASE_DIR/setup.py" thinking status 2>/dev/null | grep -oP '(thinking:\\s*.*)' | head -1 || echo '○ thinking: off')"
            echo ""
            echo "═════════════════════════════════════════════════════════════════════"
            echo "  OpenCode UNLIMITED"
            echo "  $THINKING_MODE"
            echo "  API: http://127.0.0.1:8080/v1  |  Proxy: opencode2api + WARP"
            echo "═════════════════════════════════════════════════════════════════════"
            echo ""
            if [ "$2" = "--continue" ]; then
                exec "$CLI" --continue
            else
                exec "$CLI"
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
            echo "Usage: opencode-unlimited [start|stop|restart|status|install]"
            echo "       Run with no args for the interactive menu."
            exit 1
            ;;
    esac
    exit 0
fi

# ── Interactive menu mode ──
while true; do
    show_main_menu
    read -r choice
    case "$choice" in
        1) handle_rea ;;
        2) handle_opencode_unlimited ;;
        3) "$PROXY" doctor ; read -r -p "  Press Enter to continue..." _ ;;
        4) "$PROXY" rate-limit ; read -r -p "  Press Enter to continue..." _ ;;
        5) python3 "$BASE_DIR/setup.py" thinking status ; read -r -p "  Press Enter to continue..." _ ;;
        6) echo ""
           echo "  Skills commands:"
           echo "    list   | install | sync | search <term>"
           echo "    categories | show <name> | add <name>"
           echo "    remove <name> | export <file> | import <file>"
           read -r -p "  Run which? " skill_cmd
           case "$skill_cmd" in
               list|install|sync|categories) "$PROXY" skills "$skill_cmd" ;;
               search|show|add|remove|export|import)
                   read -r -p "  Enter argument: " skill_arg
                   "$PROXY" skills "$skill_cmd" "$skill_arg" ;;
               *) echo "  Unknown command." ;;
           esac
           read -r -p "  Press Enter to continue..." _ ;;
        7) echo ""
           echo "  Models commands:"
           echo "    list   | best   | model <name>   | bench <model>"
           read -r -p "  Run which? " model_cmd
           case "$model_cmd" in
               list|best) "$PROXY" models "$model_cmd" ;;
               model|bench)
                   read -r -p "  Enter model name: " model_arg
                   "$PROXY" "$model_cmd" "$model_arg" ;;
               *) echo "  Unknown command." ;;
           esac
           read -r -p "  Press Enter to continue..." _ ;;
        8) echo ""
           echo "  Zoom commands:"
           echo "    zoom-in   | zoom-out   | zoom-reset"
           read -r -p "  Run which? " zoom_cmd
           case "$zoom_cmd" in
               zoom-in|zoom-out|zoom-reset) "$PROXY" "$zoom_cmd" ;;
               *) echo "  Unknown command." ;;
           esac
           read -r -p "  Press Enter to continue..." _ ;;
        9) "$PROXY" fix-dns ; read -r -p "  Press Enter to continue..." _ ;;
        10) "$PROXY" autostart "${2:-status}" ; read -r -p "  Press Enter to continue..." _ ;;
        0) echo "  Goodbye!" ; exit 0 ;;
        *) echo "  Invalid option." ; sleep 1 ;;
    esac
done
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

    if env == "termux":
        if not which("grun"):
            warn("grun not found — OpenCode CLI won't run on Termux without glibc-runner")
            warn("Install with: pkg install glibc-repo glibc-runner")

    if env == "termux":
        OPENCODE_WRAPPER.write_text(OPENCODE_WRAPPER_SH)
    else:
        thinking_cmd = f"python3 '{BASE_DIR / 'setup.py'}' thinking status 2>/dev/null | grep -oP '(thinking:\\\\s*.*)' | head -1 || echo '○ thinking: off'"
        OPENCODE_WRAPPER.write_text(f"""#!/usr/bin/env bash
# OpenCode CLI wrapper — passes all flags through to opencode-bin.
# Supports: opencode --continue  (resume previous session)
# Shows thinking indicator banner before launching OpenCode CLI.
THINKING_MODE="{thinking_cmd}"
echo ""
echo "═════════════════════════════════════════════════════════════════════"
echo "  OpenCode UNLIMITED"
echo "  $THINKING_MODE"
echo "  API: http://127.0.0.1:8080/v1  |  Proxy: opencode2api + WARP"
echo "═════════════════════════════════════════════════════════════════════"
echo ""
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


def write_opencode_config(force=False):
    """Write OpenCode config pointing to the local proxy.

    Always updates model + baseURL so OpenCode routes through opencode2api
    (with WARP rotation) instead of hitting OpenCode's free-tier rate limit.
    Includes thinking indicator in system_prompt so it shows inside CLI.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    thinking_text = thinking_indicator_plain()

    if OPENCODE_JSONC.exists() and not force:
        try:
            current = json.loads(OPENCODE_JSONC.read_text())
            current["model"] = "opencode-unlimited-proxy/deepseek-v4.1-flash-free"
            current.setdefault("provider", {}).setdefault("opencode-unlimited-proxy", {})["options"] = {
                "baseURL": "http://127.0.0.1:8080/v1",
                "apiKey": "local-test-key",
            }
            # Prepend thinking indicator to existing system_prompt
            existing_sp = current.get("system_prompt", "") or ""
            if thinking_text not in existing_sp:
                current["system_prompt"] = f"{thinking_text}\n\n{existing_sp}".strip()
            OPENCODE_JSONC.write_text(json.dumps(current, indent=2))
            info("Updated existing opencode.jsonc to route through local proxy.")
        except Exception:
            config = {
                "$schema": "https://opencode.ai/config.json",
                "model": "opencode-unlimited-proxy/deepseek-v4.1-flash-free",
                "system_prompt": thinking_text,
                "permission": {
                    "*": "allow", "bash": "allow", "read": "allow", "write": "allow",
                    "edit": "allow", "glob": "allow", "grep": "allow", "list": "allow", "websearch": "allow"
                },
                "provider": {
                    "opencode-unlimited-proxy": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "opencode-unlimited-proxy",
                        "options": {"baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local-test-key"},
                        "models": {
                            "beam-free": {}, "big-pickle": {}, "crouton-alpha-free": {},
                            "deepseek-v4.1-flash-free": {}, "flint-40b-free": {}, "glm-5.3-flash-free": {},
                            "mimo-v2.6-flash-free": {}, "nemotron-3.5-lightning-free": {},
                            "nemotron-3.5-super-vl-free": {}, "pulse-alpha-free": {}
                        }
                    }
                }
            }
            OPENCODE_JSONC.write_text(json.dumps(config, indent=2))
            info("Wrote fresh opencode.jsonc routing through local proxy.")
    else:
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": "opencode-unlimited-proxy/deepseek-v4.1-flash-free",
            "system_prompt": thinking_text,
            "permission": {
                "*": "allow", "bash": "allow", "read": "allow", "write": "allow",
                "edit": "allow", "glob": "allow", "grep": "allow", "list": "allow", "websearch": "allow"
            },
            "provider": {
                "opencode-unlimited-proxy": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "opencode-unlimited-proxy",
                    "options": {"baseURL": "http://127.0.0.1:8080/v1", "apiKey": "local-test-key"},
                    "models": {
                        "beam-free": {}, "big-pickle": {}, "crouton-alpha-free": {},
                        "deepseek-v4.1-flash-free": {}, "flint-40b-free": {}, "glm-5.3-flash-free": {},
                        "mimo-v2.6-flash-free": {}, "nemotron-3.5-lightning-free": {},
                        "nemotron-3.5-super-vl-free": {}, "pulse-alpha-free": {}
                    }
                }
            }
        }
        OPENCODE_JSONC.write_text(json.dumps(config, indent=2))
        success("Wrote opencode.jsonc routing through local proxy.")


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


def test_model(model):
    header(f"Testing Model: {model}")
    if not health_ok():
        error(f"Proxy not reachable at {API_URL}/healthz — is it running?")
        info("Start it: opencode-proxy start")
        info("Fix DNS if needed: opencode-proxy fix-dns")
        return
    info("Sending test prompt through proxy...")
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


def show_logs():
    header("Proxy Logs")
    if LOG_FILE.exists():
        print(LOG_FILE.read_text(errors="replace")[-5000:])
    else:
        warn("No log file found.")


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


def do_uninstall():
    header("Uninstalling OpenCode UNLIMITED")
    stop_daemon()
    for p in [PID_FILE, LOG_FILE, CONFIG_FILE, DAEMON_FILE, ENGINE_BIN,
              OPENCODE_BIN, OPENCODE_WRAPPER, MANAGER_FILE, OPENCODE_JSONC,
              OPENCODE_UNLIMITED]:
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


def do_backup():
    header("Backup")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = BACKUP_DIR / f"opencode-backup-{stamp}.tar.gz"
    items = [CONFIG_FILE, OPENCODE_JSONC, BASE_DIR / "setup.py", SKILLS_DIR]
    with tarfile.open(archive, "w:gz") as tar:
        for item in items:
            if item.exists():
                tar.add(item, arcname=item.name)
    success(f"Backup saved to {archive}")


def do_restore(archive_path=""):
    header("Restore")
    if not archive_path:
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


def do_version():
    header("Version Info")
    info(f"setup.py: OpenCode UNLIMITED")
    info(f"Engine  : opencode2api {ENGINE_VER}")
    info(f"CLI     : OpenCode CLI 1.19.5")
    info(f"Arch    : {ARCH}")
    info(f"Env     : {detect_env()}")


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


def do_install_dry_run():
    header("Dry-Run Install")
    check_arch()
    detect_env()
    install_packages(dry_run=True)
    install_engine(dry_run=True)
    install_opencode_cli(dry_run=True)
    info("[dry-run] Would write config, manager, wrapper, PATH")
    success("Dry-run complete — nothing was changed.")


def do_install():
    check_arch()
    header("OpenCode UNLIMITED Setup")
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(SETUP_URL, BASE_DIR / "setup.py")
    except Exception:
        pass
    install_packages()
    install_engine()
    install_rea()
    write_daemon_spawner()
    write_config()
    write_manager()
    write_unlimited_launcher()
    write_skills()
    install_opencode_cli()
    write_opencode_config(force=True)
    ensure_path()
    header("Setup Complete!")
    success("Run 'opencode-unlimited' to start gateway + CLI together.")
    info("Or use 'opencode-proxy start' then 'opencode' separately.")
    info("Manage: 'opencode-unlimited {start|stop|restart|status}'")
    info("Skills:  'opencode-proxy skills {list|install|sync|search|categories|show|add|remove|apply-skill}'")
    info("Models:  'opencode-proxy models {list|best}'")
    info("Model:   'opencode-proxy model <name>'")
    info("Config:  'opencode-proxy config'")
    info("Doctor:  'opencode-proxy doctor'")
    info("Fix DNS: 'opencode-proxy fix-dns'  (if WARP/proxy can't connect)")
    info("Zoom:    'opencode-proxy zoom-in' | 'zoom-out' | 'zoom-reset'  (Termux font size)")
    info("Thinking: 'opencode-proxy thinking <mode>'  (low, medium, max — DeepThink for DeepSeek)")
    info("          'opencode-proxy thinking status'  (show current thinking indicator)")
    info("REA:      'opencode-proxy rea {setup|analyze|update|help|status|connect}'  (Reverse Engineer Anything)")
    info("Rate-limit: 'opencode-proxy rate-limit'  (scan proxy logs for 429/rate-limit events)")
    info("Autostart:  'opencode-proxy autostart {enable|disable|status}'  (start proxy on device boot)")


def main():
    ap = argparse.ArgumentParser(description="OpenCode UNLIMITED all-in-one setup")
    ap.add_argument("action", nargs="?",
                    choices=["install", "start", "stop", "restart", "status",
                             "test", "bench", "logs", "update", "uninstall",
                             "backup", "restore", "watchdog", "version",
                             "validate", "dry-run", "skills", "models",
                             "model", "config", "doctor", "sync",
                             "apply-skill", "continue", "fix-dns",
                             "zoom-in", "zoom-out", "zoom-reset",
                             "thinking", "rea", "rate-limit", "autostart"],
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
    elif args.action == "bench":
        do_bench(args.model)
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
    elif args.action == "model":
        do_model(args.model)
    elif args.action == "config":
        do_config()
    elif args.action == "doctor":
        do_doctor()
    elif args.action == "sync":
        do_sync()
    elif args.action == "apply-skill":
        do_skills("apply-skill", args.skill_name)
    elif args.action == "continue":
        do_continue()
    elif args.action == "fix-dns":
        do_fix_dns()
    elif args.action == "zoom-in":
        do_zoom_in()
    elif args.action == "zoom-out":
        do_zoom_out()
    elif args.action == "zoom-reset":
        do_zoom_reset()
    elif args.action == "thinking":
        do_thinking(args.model)
    elif args.action == "rea":
        do_rea(args.model, args.archive)
    elif args.action == "rate-limit":
        do_rate_limit()
    elif args.action == "autostart":
        do_autostart(args.model)


if __name__ == "__main__":
    main()