"""
Run the Semaphore Lab web interface locally (the same code Vercel runs).

    python server.py                 start on http://localhost:8000 and open the browser
    python server.py --port 9000     choose another port
    python server.py --no-browser    do not open a browser window

Uses only the Python standard library.  The API endpoints are implemented in
webcore.py; on Vercel they are served by the thin wrappers in api/.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from webcore import ROOT, ApiHandler

INDEX = ROOT / "public" / "index.html"


class LocalHandler(ApiHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        return super().do_GET()


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    """Bind to the first free port starting at ``port``."""
    last_error: Optional[OSError] = None
    for candidate in range(port, port + 20):
        try:
            server = ThreadingHTTPServer((host, candidate), LocalHandler)
            server.daemon_threads = True
            return server
        except OSError as exc:
            last_error = exc
    raise SystemExit(f"Could not open a port between {port} and {port + 19}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Semaphore Lab - local web interface")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    parser.add_argument("--port", type=int, default=8000, help="first port to try (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args()

    server = make_server(args.host, args.port)
    url = f"http://localhost:{server.server_address[1]}"
    print("=" * 56)
    print("  Semaphore Lab is running")
    print(f"  Open:  {url}")
    print("  Stop:  press Ctrl+C in this terminal")
    print("=" * 56, flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ...")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
