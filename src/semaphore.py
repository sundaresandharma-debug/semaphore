"""
Custom semaphores, built from scratch (no threading.Semaphore, no
threading.BoundedSemaphore, no multiprocessing.Semaphore).

Only two low-level primitives are used:

* ``threading.Lock``  - makes every read/modify/write of the semaphore's
  internal state atomic (a tiny critical section, never held while sleeping).
* ``threading.Event`` - one per blocked thread; the thread sleeps on it
  (no busy-waiting, no polling, no sleep loops) until it is woken.

--------------------------------------------------------------------------
INTERNAL STATE
--------------------------------------------------------------------------
    _value    number of permits that are available right now      (int >= 0)
    _waiters  FIFO queue (collections.deque) of blocked threads; each entry
              is a _Waiter holding its own Event
    _lock     protects _value and _waiters

INVARIANTS (true whenever _lock is not held)
    I1.  _value >= 0
    I2.  _value > 0  implies  _waiters is empty
         (a permit is never left lying around while somebody is queued)
    I3.  every queued waiter is woken by exactly one signal() or by abort()
    I4.  permits are conserved:
         initial + (#signal calls) - (#wait calls that got a permit) = _value
         (a permit handed straight to a waiter counts as "got a permit")

--------------------------------------------------------------------------
THE ALGORITHM  (wait and signal are designed as a pair)
--------------------------------------------------------------------------
    wait():
        lock
            if _value > 0:                 # fast path
                _value -= 1
                unlock; return True
            w = new waiter                 # slow path: must block
            _waiters.append(w)             # joins the BACK of the queue
        unlock
        w.event.wait()                     # sleeps; the lock is NOT held
        return True                        # woken => the permit is ours

    signal():
        lock
            if _waiters is not empty:      # somebody is waiting
                w = _waiters.popleft()     # FRONT of the queue (FIFO)
                w.granted = True
                w.event.set()              # DIRECT HAND-OFF of the permit.
                                           # _value is NOT incremented, so no
                                           # newcomer can steal it ("barging")
            else:
                _value += 1                # nobody waiting: store the permit
        unlock

WHY THERE ARE NO LOST WAKE-UPS
    The waiter is put in the queue *inside the same critical section* in which
    it saw ``_value == 0``.  A signal() therefore either runs before that
    critical section (and then ``_value`` was > 0, so wait() never blocks) or
    after it (and then the waiter is already in the queue and gets woken).
    There is no gap between "decide to sleep" and "become wakeable".
    ``Event.set()`` is remembered, so even if signal() runs before the waiter
    reaches ``event.wait()`` the waiter will not sleep.

TIMEOUTS
    A timed-out waiter must remove itself from the queue.  It does so under
    the lock and first checks whether a signal() granted it a permit in the
    meantime; if so the timeout is ignored and wait() returns True.  A permit
    is therefore never lost and never delivered to a thread that gave up.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Deque, Optional

__all__ = [
    "Semaphore",
    "BinarySemaphore",
    "SemaphoreError",
    "SemaphoreOverflowError",
    "SemaphoreAborted",
]

# tracer(name, operation, value_after, waiting_after)
Tracer = Callable[[str, str, int, int], None]


class SemaphoreError(Exception):
    """Base class for all semaphore related errors."""


class SemaphoreOverflowError(SemaphoreError):
    """signal() would push a BinarySemaphore above 1 (a double release)."""


class SemaphoreAborted(SemaphoreError):
    """The semaphore was aborted; raised in threads blocked in (or entering) wait()."""


class _Waiter:
    """One blocked thread: its private Event plus how it was woken."""

    __slots__ = ("event", "granted", "aborted")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.granted = False   # True  -> woken by signal() holding a permit
        self.aborted = False   # True  -> woken by abort(), holds nothing


class Semaphore:
    """A fair (FIFO) counting semaphore.

    >>> s = Semaphore(2)
    >>> s.wait(); s.wait()          # takes both permits
    True
    True
    >>> s.value
    0
    >>> s.signal(); s.value
    1
    """

    #: Upper bound for the counter, or None for "unbounded". BinarySemaphore uses 1.
    _max_value: Optional[int] = None

    def __init__(self, value: int = 1, *, name: Optional[str] = None,
                 tracer: Optional[Tracer] = None) -> None:
        self._check_initial_value(value)
        self._value: int = value
        self._waiters: Deque[_Waiter] = deque()
        self._lock = threading.Lock()
        self._aborted = False
        self.name: str = name or f"{type(self).__name__.lower()}-{id(self) & 0xFFFF:04x}"
        self._tracer = tracer

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    @classmethod
    def _check_initial_value(cls, value: object) -> None:
        # bool is a subclass of int; Semaphore(True) is almost certainly a bug.
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"initial value must be an int, got {type(value).__name__}")
        if value < 0:
            raise ValueError(f"initial value must be >= 0, got {value}")

    # ------------------------------------------------------------------
    # inspection (read-only)
    # ------------------------------------------------------------------
    @property
    def value(self) -> int:
        """Permits available right now (never negative).

        Unlike textbook semaphores this counter does not go negative when
        threads are blocked; the number of blocked threads is ``waiting``.
        """
        with self._lock:
            return self._value

    @property
    def waiting(self) -> int:
        """Number of threads currently blocked in wait()."""
        with self._lock:
            return len(self._waiters)

    @property
    def aborted(self) -> bool:
        with self._lock:
            return self._aborted

    # ------------------------------------------------------------------
    # P operation
    # ------------------------------------------------------------------
    def wait(self, timeout: Optional[float] = None) -> bool:
        """Acquire one permit (classic P / down / acquire).

        Blocks while no permit is available.

        * ``timeout=None``  block as long as necessary, always returns True.
        * ``timeout=0``     never block: True if a permit was taken, else False.
        * ``timeout=t``     block at most ``t`` seconds: True if a permit was
                            taken, False if the time ran out.

        Raises SemaphoreAborted if the semaphore was aborted.
        """
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise TypeError(f"timeout must be a number or None, got {type(timeout).__name__}")
            if timeout < 0:
                raise ValueError(f"timeout must be >= 0, got {timeout}")

        # --- critical section 1: take a permit or join the queue -------
        with self._lock:
            if self._aborted:
                raise SemaphoreAborted(f"{self.name} was aborted")
            if self._value > 0:                     # fast path (I2: queue is empty)
                self._value -= 1
                self._emit("acquire")
                return True
            if timeout == 0:                        # try-wait: refuse to block
                self._emit("timeout")
                return False
            waiter = _Waiter()
            self._waiters.append(waiter)            # back of the line (FIFO)
            self._emit("block")

        # --- sleep WITHOUT holding the lock -----------------------------
        woken = waiter.event.wait(timeout)

        if not woken:
            # --- critical section 2: timed out; leave the queue safely ---
            with self._lock:
                if not waiter.event.is_set():
                    self._waiters.remove(waiter)    # still queued -> really gave up
                    self._emit("timeout")
                    return False
            # else: signal()/abort() won the race by a hair; handle it below.

        if waiter.aborted:
            raise SemaphoreAborted(f"{self.name} was aborted")
        return True   # waiter.granted: signal() handed us a permit

    def try_wait(self) -> bool:
        """Non-blocking wait(): True if a permit was taken immediately."""
        return self.wait(timeout=0)

    # ------------------------------------------------------------------
    # V operation
    # ------------------------------------------------------------------
    def signal(self) -> None:
        """Release one permit (classic V / up / release).

        If threads are blocked, the permit is handed directly to the one that
        has waited longest and the counter stays unchanged; otherwise the
        counter is incremented.  Signalling an aborted semaphore does nothing,
        so cleanup code (``finally: sem.signal()``) never raises.
        """
        with self._lock:
            if self._aborted:
                return
            if self._waiters:
                waiter = self._waiters.popleft()    # longest-waiting thread
                waiter.granted = True
                waiter.event.set()                  # wake exactly one thread
                self._emit("handoff")
            else:
                if self._max_value is not None and self._value >= self._max_value:
                    raise SemaphoreOverflowError(
                        f"{self.name}: signal() would raise the value above "
                        f"{self._max_value} (double release?)")
                self._value += 1
                self._emit("release")

    # ------------------------------------------------------------------
    # cancellation (used by watchdogs and by test clean-up)
    # ------------------------------------------------------------------
    def abort(self) -> None:
        """Wake every blocked thread with SemaphoreAborted and kill the semaphore.

        Lets a watchdog (or a failing unit test) tear down worker threads that
        would otherwise sleep forever.  Idempotent.
        """
        with self._lock:
            if self._aborted:
                return
            self._aborted = True
            while self._waiters:
                waiter = self._waiters.popleft()
                waiter.aborted = True
                waiter.event.set()
            self._emit("abort")

    # ------------------------------------------------------------------
    # context-manager support:  with sem: <critical section>
    # ------------------------------------------------------------------
    def __enter__(self) -> "Semaphore":
        self.wait()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.signal()
        return False            # never swallow exceptions

    # ------------------------------------------------------------------
    def _emit(self, op: str) -> None:
        """Report an operation to the optional tracer.

        Called while the lock is held so that trace order == real order.
        Tracers must therefore be quick and must not touch the semaphore.
        """
        if self._tracer is not None:
            try:
                self._tracer(self.name, op, self._value, len(self._waiters))
            except Exception:       # a broken tracer must never break the semaphore
                pass

    def __repr__(self) -> str:
        with self._lock:
            return (f"<{type(self).__name__} {self.name!r} value={self._value} "
                    f"waiting={len(self._waiters)}>")


class BinarySemaphore(Semaphore):
    """A semaphore whose value is only ever 0 or 1 (used as a mutex / lock).

    * The initial value must be 0 or 1.
    * ``signal()`` on a semaphore that is already 1 and has nobody waiting
      raises SemaphoreOverflowError instead of silently piling up a second
      permit - a double release would break mutual exclusion, so we make the
      bug loud.
    """

    _max_value = 1

    @classmethod
    def _check_initial_value(cls, value: object) -> None:
        super()._check_initial_value(value)
        if value not in (0, 1):
            raise ValueError(f"BinarySemaphore initial value must be 0 or 1, got {value}")

    def __init__(self, value: int = 1, *, name: Optional[str] = None,
                 tracer: Optional[Tracer] = None) -> None:
        super().__init__(value, name=name, tracer=tracer)
