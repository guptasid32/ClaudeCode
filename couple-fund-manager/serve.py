#!/usr/bin/env python3
"""LAN-accessible server for the Couple Fund Manager.

Serves the static UI AND persists shared state on the laptop in data.json,
so every device on the same Wi-Fi reads and writes the same data.

Run this from the couple-fund-manager directory:

    python3 serve.py                       # default port 8080, ./data.json
    python3 serve.py 5000                  # custom port
    python3 serve.py 5000 /path/to/data.json   # custom data file

API (used by the UI):
    GET  /api/state   ->  {"state": {...}, "version": N}
    PUT  /api/state   ->  body {"state": {...}}  ; returns {"version": N}
"""

import http.server
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
HOST = "0.0.0.0"
ROOT = Path(__file__).resolve().parent
DATA_PATH = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else (ROOT / "data.json")

_lock = threading.Lock()
_version = 0  # monotonically increases on every successful write


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_state() -> dict:
    if not DATA_PATH.exists():
        return {}
    try:
        with DATA_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            with _lock:
                self._send_json(200, {"state": _read_state(), "version": _version})
            return
        return super().do_GET()

    def do_PUT(self):
        if self.path == "/api/state":
            global _version
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self._send_json(400, {"error": f"Invalid JSON: {e}"})
                return
            state = payload.get("state", payload)
            if not isinstance(state, dict):
                self._send_json(400, {"error": "state must be a JSON object"})
                return
            with _lock:
                try:
                    _atomic_write(DATA_PATH, json.dumps(state, indent=2).encode("utf-8"))
                    _version += 1
                    self._send_json(200, {"version": _version})
                except OSError as e:
                    self._send_json(500, {"error": str(e)})
            return
        self.send_error(404)

    def do_DELETE(self):
        if self.path == "/api/state":
            global _version
            with _lock:
                try:
                    if DATA_PATH.exists():
                        DATA_PATH.unlink()
                    _version += 1
                    self._send_json(200, {"version": _version})
                except OSError as e:
                    self._send_json(500, {"error": str(e)})
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        # Quieter than default; only log non-asset paths.
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") or path in {"/"}:
            sys.stderr.write(
                "%s - %s\n" % (self.log_date_time_string(), fmt % args)
            )


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def lan_addresses():
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" in ip or ip.startswith("127."):
                continue
            addrs.add(ip)
    except socket.gaierror:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(addrs)


def main():
    global _version
    if DATA_PATH.exists():
        _version = 1  # any starting version > 0 indicates "data exists"
    with _Server((HOST, PORT), Handler) as httpd:
        print(f"Couple Fund Manager")
        print(f"  Static dir:  {ROOT}")
        print(f"  Data file:   {DATA_PATH}")
        print(f"  Local:       http://localhost:{PORT}/")
        for ip in lan_addresses():
            print(f"  Wi-Fi:       http://{ip}:{PORT}/")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
