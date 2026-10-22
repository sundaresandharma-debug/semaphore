"""
Shared backend for the web interface (used by Vercel functions in api/ and by
the local server in server.py).

Serverless functions cannot keep background threads or memory between
requests, so every endpoint here is self-contained:

* a demo run executes the REAL Python demo to completion inside one request,
  sampling the live state every ~100 ms; the browser then replays those frames
  as the animation, at the speed they actually happened;
* the playground is rebuilt on every request by replaying the list of
  wait()/signal() actions the browser sends on a fresh, real Semaphore.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demos import ALL_DEMOS, DEMOS_BY_ID  # noqa: E402
from src.semaphore import Semaphore, SemaphoreAborted  # noqa: E402
from src.synchronization import EventLog  # noqa: E402

RUN_BUDGET = 50.0          # seconds; stays under the function's maxDuration (60 s)
FRAME_EVERY = 0.1          # seconds between state samples
MAX_PLAY_ACTIONS = 300


# ----------------------------------------------------------------------
# Catalogue and source viewer
# ----------------------------------------------------------------------
def demo_metadata() -> List[dict]:
    out = []
    for demo in ALL_DEMOS:
        params = []
        for s in demo.PARAMS:
            kind = s.get("type", "int")
            params.append({"name": s["name"], "label": s["label"], "type": kind,
                           "min": s["min"], "max": s["max"],
                           "step": 1 if kind == "int" else 0.05,
                           "default": s.get("ui", s["default"]), "quick": s["default"]})
        out.append({"id": demo.ID, "title": demo.TITLE, "description": demo.DESCRIPTION,
                    "watch_for": demo.WATCH_FOR, "params": params})
    return out


# ----------------------------------------------------------------------
# Demo runs: execute to completion, record frames for replay
# ----------------------------------------------------------------------
def run_demo(demo_id: str, params: dict, record: bool = True) -> dict:
    if demo_id not in DEMOS_BY_ID:
        raise ValueError(f"unknown demo {demo_id!r}")
    allowed = {s["name"] for s in DEMOS_BY_ID[demo_id].PARAMS}
    params = {k: v for k, v in params.items() if k in allowed}   # ignore unknown keys such as "log"
    log = EventLog()
    box: Dict[str, Any] = {}

    def go() -> None:
        try:
            box["result"] = DEMOS_BY_ID[demo_id].run(log=log, **params).to_dict()
        except Exception:
            box["error"] = traceback.format_exc()

    worker = threading.Thread(target=go, daemon=True, name=f"demo-{demo_id}")
    t0 = time.monotonic()
    worker.start()
    frames: List[dict] = []
    while worker.is_alive():
        if record:
            frames.append({"t": round(time.monotonic() - t0, 3), "seq": log.event_count(),
                           "state": log.snapshot()})
        worker.join(FRAME_EVERY)
        if time.monotonic() - t0 > RUN_BUDGET and not log.cancelled:
            log.cancel()                       # stop long runs before the platform kills us
    events = log.events_since(0, EventLog.MAX_EVENTS)
    frames.append({"t": round(time.monotonic() - t0, 3), "seq": len(events), "state": log.snapshot()})
    return {"frames": frames if record else frames[-1:], "events": events,
            "result": box.get("result"), "error": box.get("error"),
            "timed_out": log.cancelled}


# ----------------------------------------------------------------------
# Playground: replay the user's actions on a fresh, real Semaphore
# ----------------------------------------------------------------------
class Playground:
    NAMES = ["A", "B", "C", "D", "E"]

    def __init__(self, value: int = 1) -> None:
        self.log = EventLog()
        self.initial = value
        self.sem = Semaphore(value, name="sem", tracer=self.log.tracer)
        self.threads: Dict[str, Dict[str, Any]] = {n: {"state": "idle", "arrival": 0} for n in self.NAMES}
        self.arrivals = 0
        self.log.log("sem", "info", f"new Semaphore({value})", channel="sem")

    def _blocked(self) -> int:
        return sum(t["state"] == "blocked" for t in self.threads.values())

    def _settle(self, entry: Optional[Dict[str, Any]] = None) -> None:
        """Wait (bounded) until every helper thread has reached its resting state."""
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if entry is not None and entry["state"] == "holding":
                return
            if self._blocked() == self.sem.waiting:
                return
            time.sleep(0.001)

    def act(self, action: str, name: Optional[str] = None) -> None:
        if action == "wait" and name in self.threads and self.threads[name]["state"] in ("idle", "released"):
            sem, entry = self.sem, self.threads[name]
            self.arrivals += 1
            entry.update(state="blocked", arrival=self.arrivals)

            def helper() -> None:
                try:
                    sem.wait()
                    entry["state"] = "holding"
                except SemaphoreAborted:
                    pass

            threading.Thread(target=helper, daemon=True, name=f"play-{name}").start()
            self._settle(entry)
        elif action == "release" and name in self.threads and self.threads[name]["state"] == "holding":
            self.threads[name]["state"] = "released"
            self.sem.signal()
            self._settle()
        elif action == "signal":
            try:
                self.sem.signal()
            except Exception as exc:
                self.log.log("sem", "info", f"signal() failed: {exc}", channel="sem")
            self._settle()

    def state(self) -> dict:
        queue = sorted((n for n, t in self.threads.items() if t["state"] == "blocked"),
                       key=lambda n: self.threads[n]["arrival"])
        return {"value": self.sem.value, "waiting": self.sem.waiting, "initial": self.initial,
                "queue": queue,
                "holding": [n for n, t in self.threads.items() if t["state"] == "holding"],
                "threads": {n: t["state"] for n, t in self.threads.items()},
                "trace": self.log.events_since(0, 400)[-40:]}

    def close(self) -> None:
        self.sem.abort()                       # wake blocked helper threads so they exit


def playground(initial: Any, actions: Any) -> dict:
    try:
        value = max(0, min(5, int(initial)))
    except (TypeError, ValueError):
        value = 1
    if not isinstance(actions, list):
        actions = []
    pg = Playground(value)
    try:
        for a in actions[:MAX_PLAY_ACTIONS]:
            if not isinstance(a, dict):
                continue
            before = pg.log.event_count()
            pg.act(str(a.get("action", "")), a.get("name"))
            t = a.get("t")
            if isinstance(t, (int, float)):    # show when the user actually clicked
                for ev in pg.log.events_since(before, 400):
                    ev["t"] = round(float(t), 2)
        return pg.state()
    finally:
        pg.close()


# ----------------------------------------------------------------------
# Rate limiting (per client, sliding window)
# ----------------------------------------------------------------------
import collections  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import secrets  # noqa: E402


LIMITS = {                     # requests per minute per client
    "run": 30, "playground": 120, "errors": 10, "default": 240,
}
_SALT = secrets.token_bytes(16)           # per process: raw IP addresses are never stored
_HITS: Dict[Tuple[str, str], collections.deque] = {}
_HITS_LOCK = threading.Lock()


def client_key(ip: str) -> str:
    return hashlib.sha256(_SALT + ip.encode("utf-8", "replace")).hexdigest()[:16]


def rate_limited(bucket: str, client: str) -> int:
    """0 if allowed, else the number of seconds to wait."""
    limit, now = LIMITS.get(bucket, LIMITS["default"]), time.monotonic()
    with _HITS_LOCK:
        hits = _HITS.setdefault((bucket, client), collections.deque())
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= limit:
            return max(1, int(60 - (now - hits[0])) + 1)
        hits.append(now)
        if len(_HITS) > 20000:                # forget idle clients
            for key in [k for k, d in _HITS.items() if not d or now - d[-1] > 60]:
                del _HITS[key]
        return 0


def log_event(level: str, **fields: Any) -> str:
    """One JSON line on stdout (Vercel shows it under the deployment's Logs)."""
    ref = "E-" + secrets.token_hex(3).upper()
    print(json.dumps({"level": level, "ref": ref, **fields}), flush=True)
    return ref


# ----------------------------------------------------------------------
# One dispatcher for every endpoint
# ----------------------------------------------------------------------
Result = Tuple[int, Any, List[str]]


def dispatch(method: str, path: str, query: Dict[str, List[str]], body: dict, client: str) -> Result:
    path = "/" + path.strip("/")
    bucket = path.split("/")[2] if path.count("/") >= 2 else "default"
    wait = rate_limited(bucket if method == "POST" else "default", client)   # strict limits only on actions
    if wait:
        return 429, {"error": f"Too many requests. Please wait {wait} seconds and try again.",
                     "retry_after": wait}, [f"Retry-After: {wait}"]
    out: List[str] = []
    try:
        if path == "/api/catalog" and method == "GET":
            return 200, demo_metadata(), out
        if path == "/api/run" and method == "POST":
            demo = str(body.get("demo"))
            if demo not in DEMOS_BY_ID:
                return 400, {"error": "Unknown demonstration."}, out
            params = body.get("params") if isinstance(body.get("params"), dict) else {}
            return 200, run_demo(demo, params, record=bool(body.get("record", True))), out
        if path == "/api/playground" and method == "POST":
            return 200, playground(body.get("initial", 1), body.get("actions")), out
        if path == "/api/errors" and method == "POST":
            def clip(key: str, n: int) -> str:
                return str(body.get(key) or "")[:n]
            ref = log_event("client_error", message=clip("message", 300), where=clip("where", 120),
                            line=clip("line", 10), view=clip("view", 40))
            return 200, {"ok": True, "ref": ref}, out
        return 404, {"error": "There is nothing at this address."}, out
    except ValueError as exc:
        return 400, {"error": str(exc)}, out


# ----------------------------------------------------------------------
# HTTP handler (Vercel's Python runtime and server.py both use this class)
# ----------------------------------------------------------------------
from http.server import BaseHTTPRequestHandler  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "SemaphoreLab/3.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[List[str]] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for line in extra or []:              # extra "Header: value" lines, e.g. Retry-After
            name, _, value = line.partition(": ")
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any, extra: Optional[List[str]] = None) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _client_ip(self) -> str:
        fwd = self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP") or ""
        return fwd.split(",")[0].strip() or self.client_address[0]


    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True                       # same-origin fetches from older browsers, curl
        return urlparse(origin).netloc == (self.headers.get("X-Forwarded-Host") or self.headers.get("Host"))

    def _handle(self, method: str) -> None:
        url = urlparse(self.path)
        try:
            body: dict = {}
            if method == "POST":
                if not self._same_origin():
                    return self._json(403, {"error": "Requests from other websites are not accepted."})
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._json(400, {"error": "Content-Type must be application/json."})
                length = int(self.headers.get("Content-Length") or 0)
                if length > 65536:
                    return self._json(413, {"error": "The request is too large."})
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._json(400, {"error": "The request was not valid JSON."})
                if not isinstance(body, dict):
                    return self._json(400, {"error": "The request must be a JSON object."})
            code, payload, extra = dispatch(method, url.path, parse_qs(url.query), body,
                                            client_key(self._client_ip()))
            self._json(code, payload, extra)
        except Exception:
            ref = log_event("server_error", path=url.path, trace=traceback.format_exc(limit=8))
            self._json(500, {"error": "Something went wrong on the server. Please try again.", "ref": ref})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")
