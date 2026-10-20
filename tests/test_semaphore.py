"""
Unit tests for the custom Semaphore and BinarySemaphore (standard ``unittest``).

How the tests stay reliable and never hang
------------------------------------------
* "Is the thread really blocked?" is answered with ``sem.waiting`` (the thread
  is in the semaphore's queue), not with sleep-and-hope.
* Blocking / waking is observed through ``threading.Event`` objects and every
  wait in the tests has a timeout (TIMEOUT seconds).
* Every worker thread is a daemon thread started through ``spawn()``.  In
  ``tearDown`` the test aborts all semaphores it created (which wakes any
  thread still blocked with SemaphoreAborted) and then joins the threads, so
  even a FAILED test cannot leave the test process hanging.
"""

from __future__ import annotations

import ast
import threading
import time
import unittest
from pathlib import Path

from src.semaphore import (BinarySemaphore, Semaphore, SemaphoreAborted,
                           SemaphoreOverflowError)

TIMEOUT = 5.0     # upper bound for anything that "should happen"


class ThreadedTestCase(unittest.TestCase):
    """Base class: tracks threads and semaphores and cleans them up."""

    def setUp(self):
        self._threads = []
        self._sems = []
        self.errors = []           # exceptions raised inside worker threads

    def make(self, cls, value, **kw):
        sem = cls(value, **kw)
        self._sems.append(sem)
        return sem

    def spawn(self, target, *args):
        def runner():
            try:
                target(*args)
            except SemaphoreAborted:
                pass                                  # normal during clean-up
            except BaseException as exc:              # real failure inside a worker
                self.errors.append(exc)
        t = threading.Thread(target=runner, daemon=True)
        self._threads.append(t)
        t.start()
        return t

    def wait_until(self, condition, what="condition"):
        """Poll (bounded) until condition() is true; fail the test on timeout."""
        deadline = time.monotonic() + TIMEOUT
        while not condition():
            if time.monotonic() > deadline:
                self.fail(f"timed out waiting for {what}")
            time.sleep(0.0005)

    def tearDown(self):
        for sem in self._sems:
            sem.abort()                               # wakes anything still blocked
        for t in self._threads:
            t.join(TIMEOUT)
        alive = [t for t in self._threads if t.is_alive()]
        self.assertFalse(alive, f"{len(alive)} worker thread(s) did not terminate")
        self.assertEqual(self.errors, [], f"exceptions in worker threads: {self.errors}")


# ======================================================================
class TestInitialisation(ThreadedTestCase):

    def test_initial_value_is_stored(self):
        """A new semaphore reports exactly the value it was created with."""
        for v in (0, 1, 5, 100):
            self.assertEqual(self.make(Semaphore, v).value, v)

    def test_default_value_is_one(self):
        """Semaphore() with no argument behaves like a mutex (value 1)."""
        self.assertEqual(self.make(Semaphore, 1).value, 1)
        self.assertEqual(Semaphore().value, 1)

    def test_new_semaphore_has_no_waiters(self):
        """Nobody is blocked on a freshly created semaphore."""
        self.assertEqual(self.make(Semaphore, 0).waiting, 0)

    def test_negative_initial_value_rejected(self):
        """A negative initial value raises ValueError."""
        with self.assertRaises(ValueError):
            Semaphore(-1)

    def test_non_integer_initial_value_rejected(self):
        """Floats, strings, None and bools raise TypeError."""
        for bad in (1.5, "3", None, True, [1]):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                Semaphore(bad)

    def test_value_property_is_read_only(self):
        """The counter cannot be assigned from outside."""
        sem = self.make(Semaphore, 1)
        with self.assertRaises(AttributeError):
            sem.value = 10

    def test_implementation_uses_no_builtin_semaphore(self):
        """semaphore.py must not use threading.Semaphore/BoundedSemaphore/multiprocessing."""
        source = (Path(__file__).resolve().parent.parent / "src" / "semaphore.py").read_text()
        tree = ast.parse(source)
        banned = {"Semaphore", "BoundedSemaphore"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in banned \
                    and isinstance(node.value, ast.Name) and node.value.id in ("threading", "multiprocessing"):
                self.fail(f"uses {node.value.id}.{node.attr}")
            if isinstance(node, ast.ImportFrom) and node.module in ("threading", "multiprocessing"):
                self.assertFalse(banned & {a.name for a in node.names}, "imports a built-in semaphore")
            if isinstance(node, ast.Import):
                self.assertNotIn("multiprocessing", {a.name for a in node.names})


# ======================================================================
class TestWaitAndSignal(ThreadedTestCase):

    def test_wait_takes_available_permit(self):
        """wait() on a positive semaphore returns at once and decrements the counter."""
        sem = self.make(Semaphore, 2)
        self.assertTrue(sem.wait())
        self.assertEqual(sem.value, 1)
        self.assertTrue(sem.wait())
        self.assertEqual(sem.value, 0)

    def test_signal_increments_when_nobody_waits(self):
        """signal() with an empty queue just stores the permit in the counter."""
        sem = self.make(Semaphore, 0)
        sem.signal()
        sem.signal()
        self.assertEqual(sem.value, 2)

    def test_wait_blocks_when_no_permit(self):
        """A thread calling wait() on a zero semaphore blocks until a signal arrives."""
        sem = self.make(Semaphore, 0)
        acquired = threading.Event()
        self.spawn(lambda: (sem.wait(), acquired.set()))
        self.wait_until(lambda: sem.waiting == 1, "thread to block")
        self.assertFalse(acquired.is_set(), "thread passed wait() without a permit")
        sem.signal()                                          # clean exit for the thread
        self.assertTrue(acquired.wait(TIMEOUT))

    def test_signal_wakes_blocked_thread(self):
        """signal() wakes a blocked thread, hands it the permit and leaves the counter at 0."""
        sem = self.make(Semaphore, 0)
        acquired = threading.Event()
        self.spawn(lambda: (sem.wait(), acquired.set()))
        self.wait_until(lambda: sem.waiting == 1, "thread to block")
        sem.signal()
        self.assertTrue(acquired.wait(TIMEOUT), "blocked thread was never woken")
        self.assertEqual(sem.waiting, 0)
        self.assertEqual(sem.value, 0, "permit was handed over, not stored")

    def test_permit_is_handed_directly_to_waiter(self):
        """With a waiter queued, a newcomer cannot steal the permit (no barging)."""
        sem = self.make(Semaphore, 0)
        got = threading.Event()
        self.spawn(lambda: (sem.wait(), got.set()))
        self.wait_until(lambda: sem.waiting == 1, "thread to block")
        sem.signal()
        self.assertFalse(sem.try_wait(), "a newcomer stole the permit meant for the waiter")
        self.assertTrue(got.wait(TIMEOUT))

    def test_each_signal_wakes_exactly_one_thread(self):
        """With three blocked threads, one signal releases exactly one of them."""
        sem = self.make(Semaphore, 0)
        woken = []
        lock = threading.Lock()
        flags = [threading.Event() for _ in range(3)]

        def worker(i):
            sem.wait()
            with lock:
                woken.append(i)
            flags[i].set()

        for i in range(3):
            self.spawn(worker, i)
            self.wait_until(lambda n=i + 1: sem.waiting == n, "thread to queue")
        sem.signal()
        self.assertTrue(flags[0].wait(TIMEOUT))
        self.wait_until(lambda: sem.waiting == 2, "two threads to stay blocked")
        self.assertEqual(len(woken), 1)

    def test_try_wait(self):
        """try_wait() takes a permit if one is free and never blocks."""
        sem = self.make(Semaphore, 1)
        self.assertTrue(sem.try_wait())
        self.assertFalse(sem.try_wait())
        self.assertEqual(sem.value, 0)

    def test_timeout_expires_and_leaves_queue_clean(self):
        """wait(timeout) returns False after the time runs out and removes the waiter."""
        sem = self.make(Semaphore, 0)
        t0 = time.monotonic()
        self.assertFalse(sem.wait(timeout=0.05))
        self.assertGreaterEqual(time.monotonic() - t0, 0.04)
        self.assertEqual(sem.waiting, 0, "timed-out waiter was left in the queue")
        sem.signal()
        self.assertEqual(sem.value, 1, "permit must be kept, not given to the dead waiter")

    def test_wait_with_timeout_succeeds_if_permit_arrives(self):
        """A timed wait that gets a permit in time returns True."""
        sem = self.make(Semaphore, 0)
        result = []
        done = threading.Event()
        self.spawn(lambda: (result.append(sem.wait(timeout=TIMEOUT)), done.set()))
        self.wait_until(lambda: sem.waiting == 1, "thread to block")
        sem.signal()
        self.assertTrue(done.wait(TIMEOUT))
        self.assertEqual(result, [True])

    def test_invalid_timeouts_rejected(self):
        """Negative or non-numeric timeouts raise ValueError / TypeError."""
        sem = self.make(Semaphore, 1)
        with self.assertRaises(ValueError):
            sem.wait(timeout=-1)
        with self.assertRaises(TypeError):
            sem.wait(timeout="soon")

    def test_abort_wakes_blocked_threads_with_exception(self):
        """abort() wakes blocked threads with SemaphoreAborted; later wait() raises at once."""
        sem = self.make(Semaphore, 0)
        outcomes = []
        flag = threading.Event()

        def worker():
            try:
                sem.wait()
                outcomes.append("acquired")
            except SemaphoreAborted:
                outcomes.append("aborted")
            flag.set()

        self.spawn(worker)
        self.wait_until(lambda: sem.waiting == 1, "thread to block")
        sem.abort()
        self.assertTrue(flag.wait(TIMEOUT))
        self.assertEqual(outcomes, ["aborted"])
        with self.assertRaises(SemaphoreAborted):
            sem.wait()
        sem.signal()          # signalling a dead semaphore must be harmless


# ======================================================================
class TestFairnessAndCompetition(ThreadedTestCase):

    def test_fifo_wake_order(self):
        """Threads are woken in exactly the order in which they started waiting."""
        sem = self.make(Semaphore, 0)
        n = 8
        order = []
        recorded = [threading.Event() for _ in range(n)]

        def worker(i):
            sem.wait()
            order.append(i)           # only one thread runs at a time here (we signal one by one)
            recorded[i].set()

        for i in range(n):
            self.spawn(worker, i)
            self.wait_until(lambda k=i + 1: sem.waiting == k, "thread to queue")
        for i in range(n):
            sem.signal()
            self.assertTrue(recorded[i].wait(TIMEOUT), f"thread {i} not woken in turn")
        self.assertEqual(order, list(range(n)))

    def test_threads_competing_for_limited_permits(self):
        """With 3 permits and 12 threads, never more than 3 are inside at once; all finish."""
        sem = self.make(Semaphore, 3)
        lock = threading.Lock()
        state = {"inside": 0, "max": 0, "done": 0}

        def worker():
            for _ in range(20):
                with sem:
                    with lock:
                        state["inside"] += 1
                        state["max"] = max(state["max"], state["inside"])
                    time.sleep(0)
                    with lock:
                        state["inside"] -= 1
            with lock:
                state["done"] += 1

        for _ in range(12):
            self.spawn(worker)
        self.wait_until(lambda: state["done"] == 12, "all workers to finish")
        self.assertLessEqual(state["max"], 3)
        self.assertEqual(sem.value, 3)
        self.assertEqual(sem.waiting, 0)

    def test_ping_pong_has_no_lost_wakeups(self):
        """Two threads hand a token back and forth 2000 times; any lost wake-up would hang."""
        ping, pong = self.make(Semaphore, 0), self.make(Semaphore, 0)
        rounds = 2000
        finished = threading.Event()

        def a():
            for _ in range(rounds):
                ping.signal()
                self.assertTrue(pong.wait(timeout=TIMEOUT), "lost wake-up (a)")

        def b():
            for _ in range(rounds):
                self.assertTrue(ping.wait(timeout=TIMEOUT), "lost wake-up (b)")
                pong.signal()
            finished.set()

        self.spawn(a)
        self.spawn(b)
        self.assertTrue(finished.wait(TIMEOUT * 2))

    def test_signal_before_wait_is_remembered(self):
        """A signal sent before anybody waits is not lost: the later wait() passes at once."""
        sem = self.make(Semaphore, 0)
        sem.signal()
        self.assertTrue(sem.wait(timeout=0.5))

    def test_timeout_racing_with_signal_never_loses_a_permit(self):
        """Hammer timeouts against signals: permits issued == permits received + left over."""
        sem = self.make(Semaphore, 0)
        got = []
        stop = threading.Event()

        def taker():
            count = 0
            while not stop.is_set():
                if sem.wait(timeout=0.0005):
                    count += 1
            got.append(count)

        takers = [self.spawn(taker) for _ in range(4)]
        sent = 3000
        for _ in range(sent):
            sem.signal()
        deadline = time.monotonic() + TIMEOUT
        while sem.value > 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        stop.set()
        for t in takers:
            t.join(TIMEOUT)
        self.assertEqual(sum(got) + sem.value, sent, "a permit was lost or duplicated")


# ======================================================================
class TestBinarySemaphore(ThreadedTestCase):

    def test_valid_initial_values(self):
        """BinarySemaphore accepts 0 and 1."""
        self.assertEqual(self.make(BinarySemaphore, 0).value, 0)
        self.assertEqual(self.make(BinarySemaphore, 1).value, 1)

    def test_invalid_initial_values(self):
        """Anything but 0/1 is rejected (ValueError for numbers, TypeError for other types)."""
        for bad in (2, -1, 10):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                BinarySemaphore(bad)
        for bad in ("1", 1.0, None, True):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                BinarySemaphore(bad)

    def test_repeated_signal_never_exceeds_one(self):
        """A second signal() on a free binary semaphore raises and the value stays 1."""
        sem = self.make(BinarySemaphore, 0)
        sem.signal()
        self.assertEqual(sem.value, 1)
        with self.assertRaises(SemaphoreOverflowError):
            sem.signal()
        self.assertEqual(sem.value, 1)

    def test_signal_on_initial_one_overflows(self):
        """BinarySemaphore(1).signal() is a double release and is reported."""
        with self.assertRaises(SemaphoreOverflowError):
            BinarySemaphore(1).signal()

    def test_wait_then_signal_cycle(self):
        """wait() makes it 0, signal() makes it 1 again, repeatedly."""
        sem = self.make(BinarySemaphore, 1)
        for _ in range(100):
            sem.wait()
            self.assertEqual(sem.value, 0)
            sem.signal()
            self.assertEqual(sem.value, 1)

    def test_blocks_second_thread_until_released(self):
        """While one thread holds the mutex a second one blocks, then proceeds on release."""
        sem = self.make(BinarySemaphore, 1)
        sem.wait()
        entered = threading.Event()
        self.spawn(lambda: (sem.wait(), entered.set(), sem.signal()))
        self.wait_until(lambda: sem.waiting == 1, "second thread to block")
        self.assertFalse(entered.is_set())
        sem.signal()
        self.assertTrue(entered.wait(TIMEOUT))

    def test_handoff_with_waiter_does_not_trigger_overflow(self):
        """Releasing a binary semaphore that has a waiter hands the permit over (no overflow)."""
        sem = self.make(BinarySemaphore, 0)
        done = threading.Event()
        self.spawn(lambda: (sem.wait(), done.set()))
        self.wait_until(lambda: sem.waiting == 1, "thread to block")
        sem.signal()
        self.assertTrue(done.wait(TIMEOUT))
        self.assertEqual(sem.value, 0)


# ======================================================================
class TestContextManager(ThreadedTestCase):

    def test_with_statement_acquires_and_releases(self):
        """Entering takes a permit, leaving gives it back."""
        sem = self.make(Semaphore, 1)
        with sem:
            self.assertEqual(sem.value, 0)
        self.assertEqual(sem.value, 1)

    def test_released_even_when_body_raises(self):
        """The permit is returned and the exception still propagates."""
        sem = self.make(BinarySemaphore, 1)
        with self.assertRaises(RuntimeError):
            with sem:
                raise RuntimeError("boom")
        self.assertEqual(sem.value, 1)

    def test_with_blocks_when_unavailable(self):
        """'with sem:' blocks like wait() when no permit is free."""
        sem = self.make(BinarySemaphore, 0)
        inside = threading.Event()

        def worker():
            with sem:
                inside.set()

        self.spawn(worker)
        self.wait_until(lambda: sem.waiting == 1, "thread to block in 'with'")
        self.assertFalse(inside.is_set())
        sem.signal()
        self.assertTrue(inside.wait(TIMEOUT))


# ======================================================================
class TestConcurrentLoad(ThreadedTestCase):

    def test_shared_counter_is_exact_with_binary_semaphore(self):
        """8 threads x 3000 read-modify-write increments under a mutex give exactly 24000."""
        mutex = self.make(BinarySemaphore, 1)
        counter = {"n": 0}
        threads, per_thread = 8, 3000

        def worker():
            for i in range(per_thread):
                with mutex:
                    tmp = counter["n"]
                    if i % 97 == 0:
                        time.sleep(0)      # force a thread switch inside the critical section
                    counter["n"] = tmp + 1

        workers = [self.spawn(worker) for _ in range(threads)]
        for w in workers:
            w.join(TIMEOUT * 6)
        self.assertEqual(counter["n"], threads * per_thread)
        self.assertEqual(mutex.value, 1)

    def test_mutual_exclusion_is_never_violated(self):
        """At no moment are two threads inside a BinarySemaphore-protected section."""
        mutex = self.make(BinarySemaphore, 1)
        state = {"inside": 0, "max": 0}

        def worker():
            for _ in range(500):
                with mutex:
                    state["inside"] += 1
                    state["max"] = max(state["max"], state["inside"])
                    time.sleep(0)
                    state["inside"] -= 1

        workers = [self.spawn(worker) for _ in range(10)]
        for w in workers:
            w.join(TIMEOUT * 4)
        self.assertEqual(state["max"], 1)

    def test_stress_many_threads(self):
        """150 threads x 40 acquire/release cycles on a 5-permit semaphore: bound holds, no leaks."""
        sem = self.make(Semaphore, 5)
        lock = threading.Lock()
        state = {"inside": 0, "max": 0, "ops": 0}

        def worker():
            for _ in range(40):
                sem.wait()
                with lock:
                    state["inside"] += 1
                    state["max"] = max(state["max"], state["inside"])
                    state["ops"] += 1
                with lock:
                    state["inside"] -= 1
                sem.signal()

        workers = [self.spawn(worker) for _ in range(150)]
        for w in workers:
            w.join(TIMEOUT * 6)
        self.assertEqual(state["ops"], 150 * 40)
        self.assertLessEqual(state["max"], 5)
        self.assertEqual(sem.value, 5)
        self.assertEqual(sem.waiting, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
