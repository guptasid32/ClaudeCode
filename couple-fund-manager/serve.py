#!/usr/bin/env python3
"""Tiny LAN-accessible static server for the Couple Fund Manager.

Run this from the couple-fund-manager directory:

    python3 serve.py            # default port 8080
    python3 serve.py 5000       # custom port

It binds to 0.0.0.0 so any device on the same Wi-Fi can open the app.
"""

import http.server
import socket
import socketserver
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
HOST = "0.0.0.0"
ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        # No-cache so phones/tablets always get the latest version
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def lan_addresses():
    addrs = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" in ip:
                continue
            if ip.startswith("127."):
                continue
            addrs.add(ip)
    except socket.gaierror:
        pass
    # Fallback: open a UDP socket to a public IP to learn the local routing IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addrs.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(addrs)


def main():
    with socketserver.ThreadingTCPServer((HOST, PORT), Handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"Couple Fund Manager — serving {ROOT}")
        print(f"  Local:   http://localhost:{PORT}/")
        for ip in lan_addresses():
            print(f"  Wi-Fi:   http://{ip}:{PORT}/")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
