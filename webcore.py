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
import unittest
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


def source_files() -> List[str]:
    files = ["README.md", "VIVA.md", "main.py", "webcore.py", "server.py"]
    for folder in ("src", "demos", "tests", "api"):
        files += sorted(f"{folder}/{p.name}" for p in (ROOT / folder).glob("*.py")
                        if p.name != "__init__.py" or folder == "src")
    return [f for f in files if (ROOT / f).is_file()]


def source_list() -> List[dict]:
    return [{"file": f, "lines": (ROOT / f).read_text(encoding="utf-8").count("\n") + 1}
            for f in source_files()]


# ----------------------------------------------------------------------
# Unit tests
# ----------------------------------------------------------------------
class _Collector(unittest.TestResult):
    """Collects one row per test (name, what it verifies, outcome)."""

    def __init__(self):
        super().__init__()
        self.rows: List[dict] = []

    def _row(self, test, status: str, detail: str = "") -> None:
        cls, _, name = test.id().rpartition(".")
        self.rows.append({"cls": cls.split(".")[-1], "name": name, "status": status,
                          "doc": (test.shortDescription() or "").strip(), "detail": detail})

    def addSuccess(self, test):
        super().addSuccess(test)
        self._row(test, "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._row(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._row(test, "ERROR", self._exc_info_to_string(err, test))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.rows.append({"cls": test.id().split(".")[-2], "name": test.id().split(".")[-1],
                              "status": "FAIL", "doc": str(subtest),
                              "detail": self._exc_info_to_string(err, test)})


def run_unit_tests() -> dict:
    suite = unittest.TestLoader().discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    collector = _Collector()
    started = time.monotonic()
    suite.run(collector)
    failed = sum(r["status"] == "FAIL" for r in collector.rows)
    errors = sum(r["status"] == "ERROR" for r in collector.rows)
    return {"ok": collector.wasSuccessful(), "total": collector.testsRun, "failed": failed,
            "errors": errors, "passed": collector.testsRun - failed - errors,
            "duration": round(time.monotonic() - started, 2), "rows": collector.rows}


# ----------------------------------------------------------------------
# Demo runs: execute to completion, record frames for replay
# ----------------------------------------------------------------------
def run_demo(demo_id: str, params: dict, record: bool = True) -> dict:
    if demo_id not in DEMOS_BY_ID:
        raise ValueError(f"unknown demo {demo_id!r}")
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
# One dispatcher for every endpoint
# ----------------------------------------------------------------------
def dispatch(method: str, path: str, query: Dict[str, List[str]], body: dict) -> Tuple[int, Any]:
    path = "/" + path.strip("/")
    if path == "/api/catalog" and method == "GET":
        return 200, demo_metadata()
    if path == "/api/source" and method == "GET":
        name = (query.get("file") or [""])[0]
        if not name:
            return 200, source_list()
        if name not in source_files():
            return 404, {"error": "unknown file"}
        return 200, {"file": name, "text": (ROOT / name).read_text(encoding="utf-8")}
    if path == "/api/run" and method == "POST":
        if body.get("kind") == "tests":
            return 200, run_unit_tests()
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        return 200, run_demo(str(body.get("demo")), params, record=bool(body.get("record", True)))
    if path == "/api/playground" and method == "POST":
        return 200, playground(body.get("initial", 1), body.get("actions"))
    return 404, {"error": "not found"}


# ----------------------------------------------------------------------
# HTTP handler (Vercel's Python runtime and server.py both use this class)
# ----------------------------------------------------------------------
import json  # noqa: E402
from http.server import BaseHTTPRequestHandler  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "SemaphoreLab/2.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _handle(self, method: str) -> None:
        url = urlparse(self.path)
        try:
            body: dict = {}
            if method == "POST":
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._json(400, {"error": "Content-Type must be application/json"})
                length = int(self.headers.get("Content-Length") or 0)
                if length > 65536:
                    return self._json(400, {"error": "request too large"})
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    return self._json(400, {"error": "body must be a JSON object"})
            code, payload = dispatch(method, url.path, parse_qs(url.query), body)
            self._json(code, payload)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": traceback.format_exc(limit=3)})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")
