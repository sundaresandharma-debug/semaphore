"""
Demo 1 - Race condition on a shared counter.

``counter += 1`` looks like one step but is really THREE:

        1. READ   tmp = counter
        2. ADD    tmp = tmp + 1
        3. WRITE  counter = tmp

If thread A reads 41, then thread B reads 41, then both write 42, one
increment is LOST.  Which thread gets interrupted, and when, depends on the
OS scheduler, so the wrong answer is different on every run.

We run the same workload twice:
  * WITHOUT protection  -> updates are lost, the final value varies
  * WITH a BinarySemaphore around the read-modify-write (the critical
    section) -> exactly threads x increments, every time
"""

from __future__ import annotations

import random
import threading
import time

from src.semaphore import BinarySemaphore, SemaphoreAborted
from src.synchronization import DemoResult, EventLog, join_threads, resolve_params

ID = "race"
TITLE = "Race Condition"
DESCRIPTION = ("Several threads increment one shared counter. Without a semaphore, "
               "increments are lost and the result changes from run to run. A "
               "BinarySemaphore around the critical section makes it exact.")
WATCH_FOR = [
    "Without the semaphore the counter ends BELOW the expected value, and differently each run.",
    "The read-modify-write is not atomic: two threads read the same old value and overwrite each other.",
    "With the BinarySemaphore only one thread is inside the critical section at a time, so nothing is lost.",
]
# CPython only switches threads every ~5 ms, and the read-modify-write window is a
# few nanoseconds wide, so on its own the race would show up rarely.  To make the
# effect visible within a fraction of a second we model "the scheduler may
# interrupt a thread right here" explicitly: with a small random probability the
# thread gives up the CPU between its READ and its WRITE.  The synchronized run
# uses the very same interruption, so the comparison is fair.
PREEMPT_CHANCE = 0.0005

PARAMS = [
    {"name": "threads", "label": "Threads", "type": "int", "min": 2, "max": 16, "default": 4, "ui": 4},
    {"name": "increments", "label": "Increments per thread", "type": "int",
     "min": 100, "max": 200000, "default": 20000, "ui": 20000},
    {"name": "unsync_runs", "label": "Unprotected runs (shows variation)", "type": "int",
     "min": 1, "max": 5, "default": 3, "ui": 3},
    {"name": "phase_pause", "label": "Pause between phases (s)", "type": "float",
     "min": 0.0, "max": 3.0, "default": 0.0, "ui": 0.8},
]


def _unsynchronized_worker(shared, progress, idx, increments, log):
    rng = random.Random()
    for k in range(increments):
        tmp = shared["count"]          # 1. READ
        if rng.random() < PREEMPT_CHANCE:
            time.sleep(0)              #    interrupted HERE: other threads run between our
                                       #    READ and our WRITE
        shared["count"] = tmp + 1      # 3. WRITE (may overwrite someone else's update)
        progress[idx] = k + 1
        if k % 256 == 0 and log.cancelled:
            return


def _synchronized_worker(shared, progress, idx, increments, mutex, log):
    rng = random.Random()
    try:
        for k in range(increments):
            with mutex:                # wait() ... critical section ... signal()
                tmp = shared["count"]
                if rng.random() < PREEMPT_CHANCE:
                    time.sleep(0)      # same interruption as above - now harmless, because
                                       # nobody else can enter the critical section
                shared["count"] = tmp + 1
            progress[idx] = k + 1
            if k % 256 == 0 and log.cancelled:
                return
    except SemaphoreAborted:
        return


def run(log: EventLog | None = None, **params) -> DemoResult:
    log = log or EventLog()
    p = resolve_params(PARAMS, params)
    n_threads, increments, unsync_runs = p["threads"], p["increments"], p["unsync_runs"]
    phase_pause = p["phase_pause"]
    expected = n_threads * increments
    started = time.monotonic()
    result = DemoResult(TITLE)

    log.patch("expected", expected)
    log.patch("threads", n_threads)
    log.patch("phase", "unsync")
    log.patch("unsync_results", [])
    log.log("main", "info", f"{n_threads} threads x {increments} increments -> expected {expected}")

    # ---------- phase 1: no protection ----------
    unsync_results = []
    for run_no in range(1, unsync_runs + 1):
        if log.cancelled:
            break
        shared = {"count": 0}
        progress = [0] * n_threads
        log.watch("unsync_count", lambda s=shared: s["count"])
        log.watch("progress", lambda pr=progress: list(pr))
        log.patch("phase", "unsync")
        log.patch("run_no", run_no)
        log.log("main", "info", f"Unprotected run {run_no}/{unsync_runs} ...")
        log.pause(phase_pause / 2)
        threads = [threading.Thread(target=_unsynchronized_worker, daemon=True,
                                    args=(shared, progress, i, increments, log))
                   for i in range(n_threads)]
        for t in threads:
            t.start()
        stuck = join_threads(threads, 120)
        final = shared["count"]
        unsync_results.append(final)
        log.patch("unsync_results", list(unsync_results))
        log.log("main", "violation" if final != expected else "ok",
                f"  run {run_no}: counter = {final} (expected {expected}, lost {expected - final})")
        if stuck:
            break
        log.pause(phase_pause)

    # ---------- phase 2: protected by a BinarySemaphore ----------
    sync_final = None
    if not log.cancelled:
        mutex = BinarySemaphore(1, name="mutex")
        log.watch_semaphores(mutex=mutex)
        shared = {"count": 0}
        progress = [0] * n_threads
        log.watch("sync_count", lambda s=shared: s["count"])
        log.watch("progress", lambda pr=progress: list(pr))
        log.patch("phase", "sync")
        log.log("main", "info", "Protected run (BinarySemaphore mutex) ...")
        threads = [threading.Thread(target=_synchronized_worker, daemon=True,
                                    args=(shared, progress, i, increments, mutex, log))
                   for i in range(n_threads)]
        for t in threads:
            t.start()
        stuck = join_threads(threads, 120)
        sync_final = shared["count"]
        log.log("main", "ok" if sync_final == expected else "violation",
                f"  counter = {sync_final} (expected {expected})")
        if stuck:
            log.cancel()
    log.patch("phase", "done")

    # ---------- verification ----------
    lost = [expected - r for r in unsync_results]
    result.stats = {
        "expected": expected,
        "unprotected_results": unsync_results,
        "unprotected_lost_updates": lost,
        "protected_result": sync_final,
        "protected_lost_updates": None if sync_final is None else expected - sync_final,
    }
    result.add("Protected counter equals threads x increments",
               sync_final == expected, f"{sync_final} vs expected {expected}")
    result.add("Protected run lost no updates", sync_final is not None and sync_final == expected)
    if any(lost):
        result.add("Race observed without the semaphore", True,
                   f"lost {max(lost)} updates in the worst run; results {unsync_results}", info=True)
    else:
        result.add("Race observed without the semaphore", True,
                   "no lost update this time - races are probabilistic, run again", info=True)
    if len(set(unsync_results)) > 1:
        result.add("Unprotected results differ between runs", True,
                   f"{sorted(set(unsync_results))}", info=True)
    result.notes.append("The unprotected result varies because the OS scheduler decides when a "
                        "thread is interrupted between its READ and its WRITE.")
    return result.finalize(started, cancelled=log.cancelled)
