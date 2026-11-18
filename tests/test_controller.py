#!/usr/bin/env python3
"""Checks for the controller state machine and the local lane.

The controller has no framework of its own, so this runs setup.py as a
subprocess against a throwaway HOME. It covers the parts that decide whether a
request is retried, paused, or retried forever: the free-tier rotation state,
the egress scope, and the loopback CONNECT proxy the CLI wrapper uses.

Run it with: python3 tests/test_controller.py
"""

import ast
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETUP = REPO / "setup.py"


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def block(stamp, scope, request="r", gate=""):
    return json.dumps({
        "time": iso(stamp),
        "level": "WARN",
        "msg": "free tier blocked the WARP exit; rotating it",
        "component": "upstream",
        "event": "free_tier_ip_blocked",
        "request_id": request,
        "tier": "zen",
        "upstream": gate or "https://opencode.ai/inference",
        "proxy": f"warp:{scope}",
    })


def success(stamp, scope, request="r"):
    return json.dumps({
        "time": iso(stamp),
        "level": "DEBUG",
        "msg": "anonymous WARP upstream accepted request",
        "component": "upstream",
        "event": "anonymous_attempt_succeeded",
        "request_id": request,
        "proxy": scope,
    })


def breaker(stamp, pause="15m0s"):
    return json.dumps({
        "time": iso(stamp),
        "level": "WARN",
        "msg": "anonymous lane circuit breaker opened",
        "component": "upstream",
        "event": "anonymous_breaker_open",
        "reason": "all_exits_blocked",
        "paused_for": pause,
    })


def transport(stamp, event="anonymous_attempt_transport_failed", detail="connection reset by peer"):
    return json.dumps({
        "time": iso(stamp),
        "level": "DEBUG",
        "msg": "anonymous WARP transport attempt failed",
        "component": "upstream",
        "event": event,
        "error": detail,
    })


class ControllerCase(unittest.TestCase):
    """Each test gets an empty HOME, so no state leaks between them."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nullx-test-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        (self.home / ".opencode-proxy").mkdir(parents=True)

    @property
    def base(self):
        return self.home / ".opencode-proxy"

    def write_log(self, lines):
        (self.base / "proxy.log").write_text("\n".join(lines) + "\n")

    def append_log(self, line):
        with (self.base / "proxy.log").open("a") as handle:
            handle.write(line + "\n")

    def run_setup(self, *args):
        env = dict(os.environ, HOME=str(self.home), TERM="dumb", NO_COLOR="1")
        result = subprocess.run(
            [sys.executable, str(SETUP), *args],
            capture_output=True, text=True, env=env, timeout=120,
        )
        return result.stdout + result.stderr, result.returncode

    def state(self):
        path = self.base / "rotation.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    # --- rotation state ---------------------------------------------------

    def test_one_scope_keeps_rotating(self):
        now = time.time()
        self.write_log([
            block(now - 30, "2606:4700:110:8a1c::/64"),
            # The same block is logged once per upstream gate.
            block(now - 29, "2606:4700:110:8a1c::/64"),
        ])
        out, code = self.run_setup("wall")
        state = self.state()
        self.assertEqual(code, 0, out)
        self.assertEqual(state["blocks"], 2)
        self.assertEqual(len(state["scopes"]), 1)
        self.assertFalse(state["wall"]["open"])
        self.assertIn("rotates to the next", out)

    def test_two_recent_scopes_open_the_wall(self):
        now = time.time()
        self.write_log([
            block(now - 60, "2606:4700:110:8a1c::/64"),
            block(now - 20, "2606:4700:120:9b2d::/64"),
        ])
        out, code = self.run_setup("wall")
        state = self.state()
        self.assertEqual(code, 0, out)
        self.assertTrue(state["wall"]["open"])
        self.assertGreater(state["wall"]["until"], now)
        self.assertEqual(state["view"]["distinct"], 2)
        self.assertIn("rotation is paused", out)

    def test_second_run_does_not_refold_the_log(self):
        now = time.time()
        self.write_log([
            block(now - 60, "2606:4700:110:8a1c::/64"),
            block(now - 20, "2606:4700:120:9b2d::/64"),
        ])
        self.run_setup("rotation", "status")
        first = self.state()
        self.run_setup("rotation", "status")
        second = self.state()
        self.assertEqual(second["blocks"], first["blocks"])
        self.assertEqual(second["offset"], first["offset"])
        self.assertEqual(len(second["scopes"]), 2)

    def test_a_fresh_scope_clears_the_wall(self):
        now = time.time()
        self.write_log([
            block(now - 90, "2606:4700:110:8a1c::/64"),
            block(now - 60, "2606:4700:120:9b2d::/64"),
        ])
        self.run_setup("rotation", "status")
        self.assertTrue(self.state()["wall"]["open"])
        # A third scope answered, so rotating is safe again.
        self.append_log(success(now - 10, "warp:2606:4700:130:aa3e::/64"))
        out, _ = self.run_setup("wall")
        state = self.state()
        self.assertFalse(state["wall"]["open"])
        self.assertEqual(state["wall"]["reason"], "a fresh address answered")
        self.assertIn("the wall cleared", out)

    def test_historical_blocks_do_not_open_a_wall(self):
        now = time.time()
        self.write_log([
            block(now - 7200, "2606:4700:110:8a1c::/64"),
            block(now - 7100, "2606:4700:120:9b2d::/64"),
        ])
        out, code = self.run_setup("wall")
        state = self.state()
        self.assertEqual(code, 0, out)
        self.assertFalse(state["wall"]["open"])

    def test_daily_reset_reopens_rotation(self):
        now = time.time()
        (self.base / "rotation.json").write_text(json.dumps({
            "version": 1, "offset": 0, "blocks": 4, "successes": 0,
            "last_block": now - 4000, "last_success": 0,
            "scopes": {
                "warp:2606:4700:110:8a1c::/64": {"scope": "warp:2606:4700:110:8a1c::/64", "blocks": 2, "first": now - 4000, "last": now - 4000, "success": 0},
                "warp:2606:4700:120:9b2d::/64": {"scope": "warp:2606:4700:120:9b2d::/64", "blocks": 2, "first": now - 3900, "last": now - 3900, "success": 0},
            },
            "wall": {"open": True, "since": now - 4000, "until": now - 60, "scopes": [], "cleared_at": 0, "reason": "two addresses refused"},
        }))
        out, _ = self.run_setup("wall")
        state = self.state()
        self.assertFalse(state["wall"]["open"])
        self.assertEqual(state["wall"]["reason"], "the daily reset passed")
        self.assertIn("daily reset passed", out)

    def test_breaker_is_reported(self):
        self.write_log([breaker(time.time() - 30)])
        out, code = self.run_setup("wall")
        state = self.state()
        self.assertEqual(code, 0, out)
        self.assertTrue(state["view"]["breaker"])
        self.assertIn("15m0s", out)

    def test_reset_keeps_the_log_offset(self):
        now = time.time()
        self.write_log([block(now - 30, "2606:4700:110:8a1c::/64")])
        self.run_setup("rotation", "status")
        before = self.state()
        out, code = self.run_setup("rotation", "reset")
        after = self.state()
        self.assertEqual(code, 0, out)
        self.assertEqual(after["offset"], before["offset"])
        self.assertEqual(after["blocks"], 0)
        self.assertEqual(after["scopes"], {})
        self.assertIn("cleared", out)

    def test_partially_written_line_is_read_later(self):
        now = time.time()
        first = block(now - 30, "2606:4700:110:8a1c::/64")
        (self.base / "proxy.log").write_text(first + "\n" + '{"time":"2026-11-18T')
        self.run_setup("rotation", "status")
        self.assertEqual(self.state()["offset"], len(first.encode()) + 1)
        # Once the rest of the line arrives it is folded in.
        with (self.base / "proxy.log").open("a") as handle:
            handle.write('10:00:00Z","event":"free_tier_ip_blocked","proxy":"warp:2606:4700:120:9b2d::/64"}\n')
        self.run_setup("rotation", "status")
        self.assertEqual(self.state()["blocks"], 2)

    def test_a_new_128_inside_the_same_64_is_not_a_rotation(self):
        now = time.time()
        self.write_log([
            block(now - 40, "2606:4700:110:8a1c:1:2:3:4/128"),
            block(now - 20, "2606:4700:110:8a1c:9:8:7:6/128"),
        ])
        self.run_setup("wall")
        state = self.state()
        self.assertEqual(list(state["scopes"]), ["warp:2606:4700:110:8a1c::/64"])
        self.assertFalse(state["wall"]["open"])

    def test_ipv4_scopes_are_slash_32(self):
        now = time.time()
        self.write_log([
            block(now - 40, "203.0.113.9/32"),
            block(now - 20, "203.0.113.10/32"),
        ])
        self.run_setup("wall")
        state = self.state()
        self.assertEqual(len(state["scopes"]), 2)
        self.assertTrue(state["wall"]["open"])

    def test_transport_failures_are_counted_separately(self):
        now = time.time()
        self.write_log([
            block(now - 50, "2606:4700:110:8a1c::/64"),
            transport(now - 20),
            transport(now - 19, "stream_failed", "unexpected EOF"),
        ])
        out, _ = self.run_setup("rotation", "status")
        state = self.state()
        self.assertEqual(state["transport"]["anonymous_attempt_transport_failed"]["count"], 1)
        self.assertEqual(state["transport"]["stream_failed"]["count"], 1)
        self.assertIn("transport", out)

    def test_missing_log_is_not_an_error(self):
        out, code = self.run_setup("wall")
        self.assertEqual(code, 0, out)
        self.assertIn("no free tier block", out)

    # --- egress scope -----------------------------------------------------

    def test_egress_scope_masks_and_labels(self):
        module = _load_setup()
        scope = module["egress_scope"]
        self.assertEqual(scope("warp:2606:4700:110:8a1c::/64"), "warp:2606:4700:110:8a1c::/64")
        self.assertEqual(scope("warp:2606:4700:110:8a1c:1:2:3:4"), "warp:2606:4700:110:8a1c::/64")
        self.assertEqual(scope("warp:2606:4700:110:8a1c:1:2:3:4/128"), "warp:2606:4700:110:8a1c::/64")
        self.assertEqual(scope("2606:4700:110:8a1c:1:2:3:4"), "warp:2606:4700:110:8a1c::/64")
        self.assertEqual(scope("warp:203.0.113.7"), "warp:203.0.113.7/32")
        self.assertEqual(scope("warp:203.0.113.0/24"), "warp:203.0.113.0/32")
        # A proxy route is already one scope, and an empty label stays empty.
        self.assertEqual(scope("proxy-a"), "proxy-a")
        self.assertEqual(scope(""), "")

    def test_egress_change_tracking(self):
        module = _load_setup()
        module["HOME"] = self.home
        module["BASE_DIR"] = self.base
        module["ROTATION_FILE"] = self.base / "rotation.json"
        answers = [
            "2606:4700:110:8a1c:1:2:3:4",
            "2606:4700:110:8a1c:9:9:9:9",
            "2606:4700:120:9b2d::5",
        ]
        calls = {"n": 0}

        def fake_egress(proxy=""):
            value = answers[min(calls["n"], len(answers) - 1)]
            calls["n"] += 1
            return module["ipaddress"].ip_address(value), ""

        module["public_egress"] = fake_egress
        module["do_egress"]()
        state = module["load_rotation_state"]()
        self.assertEqual(state["last_egress"], "warp:2606:4700:110:8a1c::/64")
        self.assertEqual(state["egress_changes"], 0)
        module["do_egress"]()
        state = module["load_rotation_state"]()
        self.assertEqual(state["egress_changes"], 0, "a new /128 inside the /64 is not a rotation")
        module["do_egress"]()
        state = module["load_rotation_state"]()
        self.assertEqual(state["egress_changes"], 1)
        self.assertEqual(state["last_egress"], "warp:2606:4700:120:9b2d::/64")

    # --- local lane -------------------------------------------------------

    def test_lane_script_is_written_and_parses(self):
        out, code = self.run_setup("lane", "status")
        self.assertEqual(code, 0, out)
        script = self.base / "lane_proxy.py"
        self.assertTrue(script.exists())
        compile(script.read_text(), str(script), "exec")
        # The copy is the repository file, so the two cannot drift.
        self.assertEqual(script.read_text(), (REPO / "scripts" / "lane_proxy.py").read_text())

    def test_lane_script_matches_the_repository_copy(self):
        source = (REPO / "scripts" / "lane_proxy.py").read_text()
        self.assertIn("def main(", source)
        self.assertIn("CONNECT", source)
        # The installed copy is read back by lane_script() on repair.
        self.run_setup("lane", "status")
        self.assertEqual((self.base / "lane_proxy.py").read_text(), source)

    def test_lane_forwards_connect_and_plain_http(self):
        out, code = self.run_setup("lane", "start")
        self.assertEqual(code, 0, out)
        self.addCleanup(self.run_setup, "lane", "stop")
        port = int((self.base / "lane.port").read_text().strip())

        echo, echo_port = _echo_server(lambda data: b"tunnel:" + data, read_until=None)
        http, http_port = _echo_server(
            lambda data: b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\nokay",
            read_until=b"\r\n\r\n",
        )

        # CONNECT opens a tunnel and the bytes pass through.
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(f"CONNECT 127.0.0.1:{echo_port} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        head = _read_until(client, b"\r\n\r\n")
        self.assertIn(b"200 Connection Established", head)
        client.sendall(b"hello")
        self.assertEqual(client.recv(64), b"tunnel:hello")
        client.close()

        # A plain HTTP request is rewritten to origin form.
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(
            f"GET http://127.0.0.1:{http_port}/probe HTTP/1.1\r\nHost: 127.0.0.1:{http_port}\r\nProxy-Connection: keep-alive\r\n\r\n".encode()
        )
        reply = _read_until(client, b"\r\n\r\n")
        self.assertIn(b"200 OK", reply)
        client.close()
        seen = http["last"]
        self.assertIn(b"GET /probe HTTP/1.1", seen)
        self.assertNotIn(b"proxy-connection", seen.lower())

        # A refused destination is answered, not left hanging.
        client = socket.create_connection(("127.0.0.1", port), timeout=5)
        client.sendall(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertIn(b"502", _read_until(client, b"\r\n\r\n"))
        client.close()
        echo["close"]()
        http["close"]()

    def test_wrapper_launches_the_cli_as_a_child(self):
        """The CLI must not exec, or the lane proxy outlives the session."""
        module = _load_setup()
        module["HOME"] = self.home
        module["BASE_DIR"] = self.base
        module["LOCAL_BIN"] = self.home / ".local" / "bin"
        module["OPENCODE_WRAPPER"] = module["LOCAL_BIN"] / "opencode"
        module["OPENCODE_BIN"] = module["LOCAL_BIN"] / "opencode-bin"
        module["command_dirs"] = lambda: []
        module["detect_env"] = lambda: "linux"
        module["write_opencode_wrapper"]()
        wrapper = module["OPENCODE_WRAPPER"].read_text()
        self.assertNotIn("exec ", wrapper.replace("exec grun", ""))
        self.assertIn("lane_proxy.py", wrapper)
        self.assertIn("HTTPS_PROXY", wrapper)
        compile(Path(REPO / "scripts" / "lane_proxy.py").read_text(), "lane_proxy.py", "exec")

    def test_wrapper_on_termux_skips_the_lane(self):
        module = _load_setup()
        module["HOME"] = self.home
        module["BASE_DIR"] = self.base
        module["LOCAL_BIN"] = self.home / ".local" / "bin"
        module["OPENCODE_WRAPPER"] = module["LOCAL_BIN"] / "opencode"
        module["OPENCODE_BIN"] = module["LOCAL_BIN"] / "opencode-bin"
        module["command_dirs"] = lambda: []
        module["detect_env"] = lambda: "termux"
        module["write_opencode_wrapper"]()
        wrapper = module["OPENCODE_WRAPPER"].read_text()
        self.assertIn("grun", wrapper)
        self.assertNotIn("LANE_PORT", wrapper)

    def test_lane_stop_removes_its_files(self):
        self.run_setup("lane", "start")
        out, code = self.run_setup("lane", "stop")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.base / "lane.pid").exists())
        self.assertFalse((self.base / "lane.port").exists())


def _load_setup():
    """Execute setup.py without running main, and return its globals."""
    source = SETUP.read_text()
    source = source.replace('if __name__ == "__main__":\n    main()', "")
    module = {"__name__": "setup_under_test", "__file__": str(SETUP)}
    exec(compile(source, str(SETUP), "exec"), module)
    return module


def _read_until(sock, marker):
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _echo_server(respond, read_until=b"\r\n\r\n"):
    """A tiny server: read a request, record it, answer once, and stop."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    record = {"last": b""}
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            try:
                data = _read_until(conn, read_until) if read_until else conn.recv(4096)
                record["last"] = data
                conn.sendall(respond(data))
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=serve, daemon=True).start()

    def close():
        stop.set()
        try:
            server.close()
        except OSError:
            pass

    record["close"] = close
    record["port"] = port
    return record, port


if __name__ == "__main__":
    unittest.main(verbosity=2)
