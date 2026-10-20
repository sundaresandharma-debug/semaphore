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
import json
import threading
import webbrowser
from http.server import ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlparse

from webcore import ROOT, ApiHandler

PUBLIC = ROOT / "public"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8"}


# Same headers as vercel.json, so the content security policy is tested locally too.
SECURITY_HEADERS = [h["key"] + ": " + h["value"]
                    for h in json.loads((ROOT / "vercel.json").read_text())["headers"][0]["headers"]
                    if h["key"] != "Strict-Transport-Security"]


class LocalHandler(ApiHandler):
    """Serves public/ like Vercel does (clean URLs, custom 404) and the API from webcore."""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return super().do_GET()
        files = {p.name: p for p in PUBLIC.iterdir() if p.is_file()}   # only real files, no ../ tricks
        name = "index.html" if path == "/" else path.lstrip("/")
        target = files.get(name) or files.get(name + ".html")
        if target is None or name == "404.html":
            return self._send(404, files["404.html"].read_bytes(), TYPES[".html"], SECURITY_HEADERS)
        return self._send(200, target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"),
                          SECURITY_HEADERS)


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
