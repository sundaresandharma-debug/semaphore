"""
Helpers shared by the four demonstrations, the command-line menu and the web UI.

Nothing in here is a synchronization *algorithm*; the algorithms live in
``semaphore.py`` and in the demos.  This module provides:

* EventLog     - thread-safe, timestamped log + live "state" snapshot
                 (the web UI polls it; the CLI can echo it to the console).
* DemoResult   - the verified outcome of one demonstration (checks, stats).
* join_threads - join with an overall deadline (the "watchdog" building block).
* resolve_params - validate/clamp user supplied demo parameters.
"""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from .semaphore import Semaphore


# ----------------------------------------------------------------------
# Event log
# ----------------------------------------------------------------------
class EventLog:
    """Thread-safe event log and live state holder.

    Two channels of events are kept:
      * "main"  - what the actors (threads) are doing, e.g. "P1 produced item 3"
      * "sem"   - low-level semaphore operations (acquire / block / handoff ...)
                  produced by passing ``log.tracer`` to a semaphore.

    The log uses its own plain lock.  That is fine: it only protects the log
    itself and is never part of a demonstration's synchronization logic.
    """

    MAX_EVENTS = 6000

    def __init__(self, echo: bool = False) -> None:
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._state: Dict[str, Any] = {}
        self._watchers: Dict[str, Callable[[], Any]] = {}
        self._semaphores: List[Semaphore] = []
        self._cancel = threading.Event()
        self._t0 = time.monotonic()
        self.echo = echo

    # --- events -------------------------------------------------------
    def log(self, actor: str, kind: str, msg: str, channel: str = "main") -> None:
        with self._lock:
            if len(self._events) >= self.MAX_EVENTS:
                return
            t = time.monotonic() - self._t0
            self._events.append({"seq": len(self._events) + 1, "t": round(t, 4),
                                 "actor": actor, "kind": kind, "msg": msg, "ch": channel})
            if self.echo and channel == "main":
                print(f"  [{t:7.3f}s] {actor:<9} {msg}", flush=True)

    def tracer(self, name: str, op: str, value: int, waiting: int) -> None:
        """Pass as ``tracer=log.tracer`` to a Semaphore to record its operations."""
        self.log(name, op, f"{op:<8} -> value={value} waiting={waiting}", channel="sem")

    def events_since(self, seq: int, limit: int = 800) -> List[Dict[str, Any]]:
        with self._lock:
            return self._events[seq:seq + limit]

    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    # --- live state (read by the web UI) ----------------------------------
    def patch(self, path: str, value: Any) -> None:
        """Set ``state['a']['b']['c'] = value`` for ``path == 'a.b.c'``."""
        with self._lock:
            _set_path(self._state, path, value)

    def watch(self, path: str, getter: Callable[[], Any]) -> None:
        """Evaluate ``getter()`` at snapshot time and expose it under ``path``."""
        with self._lock:
            self._watchers[path] = getter

    def watch_semaphores(self, **semaphores: Semaphore) -> None:
        """Expose each semaphore's live value/waiting count as ``sem.<name>``
        and remember it so cancel() can abort it."""
        for key, sem in semaphores.items():
            self.watch(f"sem.{key}", lambda s=sem: {"value": s.value, "waiting": s.waiting})
            with self._lock:
                self._semaphores.append(sem)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            state = copy.deepcopy(self._state)
            watchers = list(self._watchers.items())
        for path, getter in watchers:          # evaluated outside our lock
            try:
                _set_path(state, path, getter())
            except Exception:
                pass
        return state

    # --- cancellation / pacing --------------------------------------------
    def cancel(self) -> None:
        """Ask the running demo to stop and wake every blocked thread."""
        self._cancel.set()
        with self._lock:
            sems = list(self._semaphores)
        for sem in sems:
            sem.abort()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def pause(self, seconds: float) -> bool:
        """Simulate work for ``seconds`` (interruptible).  False if cancelled.

        This models *time passing* (thinking, eating, producing); it is never
        used to make the synchronization itself correct.
        """
        if seconds > 0:
            return not self._cancel.wait(seconds)
        return not self._cancel.is_set()


def _set_path(root: Dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    node = root
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------
@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    info: bool = False        # informational: shown, but never fails the demo


@dataclass
class DemoResult:
    demo: str
    status: str = "PASS"                      # PASS | FAIL | DEADLOCK | CANCELLED
    checks: List[Check] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    duration: float = 0.0

    def add(self, name: str, ok: bool, detail: str = "", info: bool = False) -> None:
        self.checks.append(Check(name, bool(ok), detail, info))

    def finalize(self, started: float, deadlock: bool = False, cancelled: bool = False) -> "DemoResult":
        self.duration = round(time.monotonic() - started, 3)
        if cancelled:
            self.status = "CANCELLED"
        elif deadlock:
            self.status = "DEADLOCK"
        elif all(c.ok for c in self.checks if not c.info):
            self.status = "PASS"
        else:
            self.status = "FAIL"
        return self

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "demo": self.demo, "status": self.status, "passed": self.passed,
            "duration": self.duration, "stats": self.stats, "notes": self.notes,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail, "info": c.info}
                       for c in self.checks],
        }


# ----------------------------------------------------------------------
# Watchdog building block
# ----------------------------------------------------------------------
def join_threads(threads: Iterable[threading.Thread], timeout: float) -> List[threading.Thread]:
    """Join all threads within ONE overall deadline.

    Returns the threads that are still alive afterwards (empty list == all
    finished).  A non-empty result is how the demos detect a hang/deadlock.
    """
    threads = list(threads)
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return [t for t in threads if t.is_alive()]


# ----------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------
def resolve_params(spec: List[Dict[str, Any]], given: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user parameters with the defaults in ``spec`` and clamp to range.

    Each spec entry: name, label, type ('int'|'float'|'bool'), min, max,
    default (used by the CLI and tests) and optional ui (default shown in the UI).
    """
    out: Dict[str, Any] = {}
    for s in spec:
        kind = s.get("type", "int")
        value = given.get(s["name"], s["default"])
        try:
            if kind == "bool":
                value = value.strip().lower() in ("1", "true", "yes", "on") \
                    if isinstance(value, str) else bool(value)
            elif kind == "float":
                value = float(value)
            else:
                value = int(value)
        except (TypeError, ValueError):
            value = s["default"]
        if kind != "bool":
            value = max(s["min"], min(s["max"], value))
        out[s["name"]] = value
    return out
