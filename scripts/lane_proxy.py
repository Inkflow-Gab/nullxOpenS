#!/usr/bin/env python3
"""Local HTTP CONNECT proxy for the OpenCode CLI.

Bun ignores socks5:// proxy variables, so the CLI cannot use the WARP client's
SOCKS listener directly. This proxy answers CONNECT and plain HTTP on a
loopback port and forwards every tunnel to its destination. It is deliberately
small: no cache, no authentication, and it only listens on 127.0.0.1.

The port is written to the file given by --port-file so the wrapper can export
the right HTTPS_PROXY. A tunnel that cannot be opened is answered with a 502
instead of a direct fallback, so a broken lane is visible rather than silently
bypassing the gateway.

This file is the source of truth: setup.py copies it to
~/.opencode-proxy/lane_proxy.py, and tests/test_controller.py drives it.
"""

import argparse
import os
import select
import socket
import socketserver
import sys
import time

BUFFER = 65536
CONNECT_TIMEOUT = 10.0


def log(message):
    stamp = time.strftime("%H:%M:%S")
    sys.stderr.write(f"[{stamp}] {message}\n")
    sys.stderr.flush()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(None)
        try:
            head = self.read_head()
        except OSError:
            return
        if not head:
            return
        try:
            # Only the request line carries the method, target and version.
            # Splitting the whole head would put every header into the version.
            first_line = head.split(bytes([13, 10]))[0]
            method, target, version = first_line.split(None, 2)
            method = method.decode("latin-1").upper()
            target = target.decode("latin-1")
        except ValueError:
            self.send_error(400, "Bad Request")
            return

        if method == "CONNECT":
            host, _, port_text = target.rpartition(":")
            if not host:
                host, port = target, 443
            else:
                try:
                    port = int(port_text)
                except ValueError:
                    self.send_error(400, "Bad Request")
                    return
            try:
                upstream = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
            except OSError as exc:
                log(f"CONNECT {host}:{port} failed: {exc}")
                self.send_error(502, "Bad Gateway")
                return
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.relay(upstream)
            return

        # A plain HTTP request: parse the absolute URL and forward it.
        url = target
        if not url.startswith("http://"):
            self.send_error(400, "Bad Request")
            return
        rest = url[len("http://"):]
        authority, _, path = rest.partition("/")
        path = "/" + path if path else "/"
        host, _, port_text = authority.partition(":")
        port = int(port_text) if port_text.isdigit() else 80
        try:
            upstream = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        except OSError as exc:
            log(f"HTTP {host}:{port} failed: {exc}")
            self.send_error(502, "Bad Gateway")
            return
        request_line = f"{method} {path} {version.decode('latin-1')}".encode("latin-1")
        # The head includes the request line as its first entry, so only the
        # header lines are filtered. The separator is built from a byte value
        # rather than an escape, so it survives every quoting context this
        # script is embedded in.
        crlf = bytes([13, 10])
        header_lines = head.split(crlf)[1:]
        keep = [
            line for line in header_lines
            if line.strip() and not line.lower().startswith((b"proxy-connection:", b"proxy-authorization:"))
        ]
        upstream.sendall(crlf.join([request_line] + keep) + crlf + crlf)
        self.relay(upstream)

    def read_head(self):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.request.recv(BUFFER)
            if not chunk:
                return b""
            data += chunk
            if len(data) > 65536:
                return b""
        return data.split(b"\r\n\r\n", 1)[0]

    def relay(self, upstream):
        sockets = [self.request, upstream]
        try:
            while True:
                readable, _, errored = select.select(sockets, [], sockets, 300)
                if errored:
                    break
                if not readable:
                    break
                for source in readable:
                    other = upstream if source is self.request else self.request
                    try:
                        chunk = source.recv(BUFFER)
                    except OSError:
                        return
                    if not chunk:
                        try:
                            other.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
                        return
                    try:
                        other.sendall(chunk)
                    except OSError:
                        return
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    def send_error(self, code, reason):
        body = f"{code} {reason}\n".encode()
        head = (
            f"HTTP/1.1 {code} {reason}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("latin-1")
        try:
            self.request.sendall(head + body)
        except OSError:
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="local lane proxy")
    parser.add_argument("port", nargs="?", type=int, default=0)
    parser.add_argument("--port-file", default="")
    args = parser.parse_args()

    server = Server(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    if args.port_file:
        tmp = args.port_file + ".tmp"
        with open(tmp, "w") as handle:
            handle.write(str(port))
        os.replace(tmp, args.port_file)
    log(f"lane listening on 127.0.0.1:{port}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
