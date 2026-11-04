#!/usr/bin/env python3
"""OpenCode Termux Unlimited — all-in-one setup & controller (Android/Termux aarch64)."""

import os
import sys
import json
import time
import shutil
import subprocess
import urllib.request
import tarfile
import argparse
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
NC = "\033[0m"


def cprint(msg, color=NC):
    print(f"{color}{msg}{NC}")


def run(cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, capture_output=capture, text=True)


def which(cmd):
    return shutil.which(cmd)


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
OPENCODE_JSONC = CONFIG_DIR / "opencode.jsonc"
BASHRC = HOME / ".bashrc"

ENGINE_VER = "v1.4.6"
ENGINE_URL = (
    "https://github.com/jasonxu114514/opencode2api/releases/download/"
    f"{ENGINE_VER}/opencode2api_{ENGINE_VER}_linux_arm64.tar.gz"
)
API_URL = "http://127.0.0.1:8080"
API_KEY = "local-test-key"
ARCH = os.uname().machine

REQUIRED_PKGS = ["curl", "jq", "proot", "termux-tools", "python"]
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

DAEMON_SPAWN = r"""#!/data/data/com.termux/files/usr/bin/python3
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

MANAGER_SH = r"""#!/data/data/com.termux/files/usr/bin/bash
BASE_DIR="$HOME/.opencode-proxy"
SETUP="$BASE_DIR/setup.py"
case "$1" in
    start)   python3 "$SETUP" start ;;
    stop)    python3 "$SETUP" stop ;;
    restart) python3 "$SETUP" restart ;;
    status)  python3 "$SETUP" status ;;
    test)    python3 "$SETUP" test "${2:-deepseek-v4.1-flash-free}" ;;
    logs)    python3 "$SETUP" logs ;;
    install) python3 "$SETUP" install ;;
    *) echo "Usage: opencode-proxy {install|start|stop|restart|status|test [model]|logs}"; exit 1 ;;
esac
"""

OPENCODE_WRAPPER_SH = r"""#!/data/data/com.termux/files/usr/bin/bash
exec /data/data/com.termux/files/usr/bin/grun "$HOME/.local/bin/opencode-bin" "$@"
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


def check_arch():
    if ARCH not in ("aarch64", "arm64"):
        cprint(f"Error: Architecture {ARCH} not supported. Requires aarch64/ARM64.", RED)
        sys.exit(1)


def install_packages():
    needed = [p for p in REQUIRED_PKGS if not which(p)]
    if not which("grun"):
        needed += GLIBC_PKGS
    if not needed:
        return
    cprint(f"Installing dependencies: {' '.join(needed)}", BLUE)
    run(["pkg", "update", "-y"])
    run(["pkg", "install", "-y"] + needed)


def download(url, dest):
    cprint(f"Downloading {url}", BLUE)
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def extract_named(tar_path, dest_dir, name_suffix):
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith(name_suffix) and not member.isdir():
                member.name = Path(member.name).name
                tar.extract(member, dest_dir)
                break


def install_engine():
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BASE_DIR / "opencode2api.tar.gz"
    download(ENGINE_URL, tmp)
    extract_named(tmp, BIN_DIR, "opencode2api")
    os.chmod(ENGINE_BIN, 0o755)
    tmp.unlink(missing_ok=True)


def write_daemon_spawner():
    DAEMON_FILE.write_text(DAEMON_SPAWN)
    os.chmod(DAEMON_FILE, 0o755)


def write_config():
    CONFIG_FILE.write_text(json.dumps(CONFIG_JSON, indent=2))


def write_manager():
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    MANAGER_FILE.write_text(MANAGER_SH)
    os.chmod(MANAGER_FILE, 0o755)


def install_opencode_cli():
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    if OPENCODE_BIN.exists():
        return
    url = "https://registry.npmjs.org/opencode-linux-arm64/-/opencode-linux-arm64-1.19.5.tgz"
    tmp = LOCAL_BIN / "opencode-cli.tgz"
    download(url, tmp)
    extract_named(tmp, LOCAL_BIN, "package/bin/opencode")
    os.chmod(OPENCODE_BIN, 0o755)
    tmp.unlink(missing_ok=True)
    OPENCODE_WRAPPER.write_text(OPENCODE_WRAPPER_SH)
    os.chmod(OPENCODE_WRAPPER, 0o755)


def write_opencode_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not OPENCODE_JSONC.exists():
        OPENCODE_JSONC.write_text(OPENCODE_JSONC_CONTENT)


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


def start_daemon():
    pid = get_pid()
    if pid:
        cprint(f"Already running (PID: {pid})", YELLOW)
        return
    cprint("Starting OpenCode Proxy daemon...", BLUE)
    pid = os.fork()
    if pid > 0:
        for _ in range(15):
            if health_ok():
                cprint("Proxy online!", GREEN)
                cprint(f"    API Endpoint: {API_URL}/v1", BLUE)
                cprint(f"    Dashboard   : http://127.0.0.1:8081", BLUE)
                cprint(f"    API Key     : {API_KEY}", BLUE)
                return
            time.sleep(1)
        cprint("Proxy failed to start. Check logs with: opencode-proxy logs", RED)
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
    cmd = ["termux-chroot", str(ENGINE_BIN), "-config", str(CONFIG_FILE)]
    try:
        os.execv(cmd[0], cmd)
    except Exception as e:
        sys.stderr.write(f"Failed to exec {cmd}: {e}\n")
        os._exit(1)


def stop_daemon():
    pid = get_pid()
    if pid:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        try:
            run(["pkill", "-f", str(ENGINE_BIN)])
        except subprocess.CalledProcessError:
            pass
        PID_FILE.unlink(missing_ok=True)
        cprint("Proxy stopped.", GREEN)
    else:
        cprint("Proxy is not running.", YELLOW)


def restart_daemon():
    stop_daemon()
    time.sleep(1)
    start_daemon()


def status_daemon():
    pid = get_pid()
    if pid:
        cprint(f"OpenCode Proxy: RUNNING (PID: {pid})", GREEN)
        try:
            data = json.loads(urllib.request.urlopen(API_URL + "/healthz", timeout=3).read().decode())
            warp = data.get("warp", {})
            cprint(f"    WARP Status : {warp.get('status', '?')} (active: {warp.get('active', '?')}, standby: {warp.get('standby', '?')})", BLUE)
            models = data.get("models", {})
            cprint(f"    Free Models : {models.get('exposed', '?')} active ({models.get('total', '?')} total upstream)", BLUE)
        except Exception:
            cprint("    API Check   : initializing or unreachable", YELLOW)
        cprint(f"    API Base    : {API_URL}/v1", BLUE)
        cprint(f"    Dashboard   : http://127.0.0.1:8081", BLUE)
    else:
        cprint("OpenCode Proxy: STOPPED", RED)


def test_model(model):
    cprint(f"Sending test prompt to '{model}'...", BLUE)
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
                        cprint("\nStream completed.", GREEN)
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
        cprint(f"Test failed: {e}", RED)


def show_logs():
    if LOG_FILE.exists():
        print(LOG_FILE.read_text(errors="replace")[-3000:])
    else:
        cprint("No log file found.", YELLOW)


def do_install():
    check_arch()
    install_packages()
    install_engine()
    write_daemon_spawner()
    write_config()
    write_manager()
    install_opencode_cli()
    write_opencode_config()
    ensure_path()
    cprint("Setup complete!", GREEN)
    cprint("Run 'opencode' to start the interactive TUI.", BLUE)
    cprint("Manage gateway with 'opencode-proxy status' or 'opencode-proxy stop'.", BLUE)


def main():
    ap = argparse.ArgumentParser(description="OpenCode Termux Unlimited all-in-one setup")
    ap.add_argument("action", nargs="?",
                    choices=["install", "start", "stop", "restart", "status", "test", "logs"],
                    default="install")
    ap.add_argument("model", nargs="?", default="deepseek-v4.1-flash-free")
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


if __name__ == "__main__":
    main()