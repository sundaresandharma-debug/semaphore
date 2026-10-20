"""
Demo 2 - Producer-Consumer with a bounded buffer.

Three semaphores coordinate everything:

    empty = Semaphore(capacity)    counts FREE slots   (producers wait on it)
    full  = Semaphore(0)           counts FILLED slots (consumers wait on it)
    mutex = BinarySemaphore(1)     one thread at a time touches the buffer

    producer:  empty.wait()  ->  mutex.wait() [ add item ] mutex.signal()  ->  full.signal()
    consumer:  full.wait()   ->  mutex.wait() [ take item ] mutex.signal() ->  empty.signal()

The ORDER matters: always wait on empty/full BEFORE the mutex. Doing it the
other way round lets a producer sit inside the mutex waiting for a free slot
while the consumers that would free one are locked out -> deadlock.

There are no poison pills: every consumer is given an exact quota, and the
quotas add up to the number of items produced, so every thread terminates.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from src.semaphore import BinarySemaphore, Semaphore, SemaphoreAborted
from src.synchronization import DemoResult, EventLog, join_threads, resolve_params

ID = "producer_consumer"
TITLE = "Producer-Consumer"
DESCRIPTION = ("Producers put items into a bounded buffer, consumers take them out. "
               "empty/full counting semaphores block producers on a full buffer and "
               "consumers on an empty one; a binary mutex protects the buffer itself.")
WATCH_FOR = [
    "empty counts free slots, full counts items: the two always add up to the capacity.",
    "When the buffer is full, producers block on empty.wait() (red) until a consumer frees a slot.",
    "When the buffer is empty, consumers block on full.wait() until a producer adds an item.",
    "Every item is consumed exactly once and the program ends without deadlock.",
]
PARAMS = [
    {"name": "producers", "label": "Producers", "type": "int", "min": 1, "max": 6, "default": 3, "ui": 3},
    {"name": "consumers", "label": "Consumers", "type": "int", "min": 1, "max": 6, "default": 2, "ui": 2},
    {"name": "items", "label": "Items per producer", "type": "int", "min": 1, "max": 40, "default": 15, "ui": 6},
    {"name": "capacity", "label": "Buffer capacity", "type": "int", "min": 1, "max": 8, "default": 4, "ui": 4},
    {"name": "produce_time", "label": "Time to produce (s)", "type": "float",
     "min": 0.0, "max": 1.0, "default": 0.0, "ui": 0.15},
    {"name": "consume_time", "label": "Time to consume (s)", "type": "float",
     "min": 0.0, "max": 1.0, "default": 0.0, "ui": 0.35},
]


def run(log: EventLog | None = None, **params) -> DemoResult:
    log = log or EventLog()
    p = resolve_params(PARAMS, params)
    n_prod, n_cons, per_prod, capacity = p["producers"], p["consumers"], p["items"], p["capacity"]
    produce_time, consume_time = p["produce_time"], p["consume_time"]
    total = n_prod * per_prod
    started = time.monotonic()
    result = DemoResult(TITLE)

    empty = Semaphore(capacity, name="empty", tracer=log.tracer)
    full = Semaphore(0, name="full", tracer=log.tracer)
    mutex = BinarySemaphore(1, name="mutex", tracer=log.tracer)
    log.watch_semaphores(empty=empty, full=full, mutex=mutex)

    buffer: deque = deque()
    produced = [[] for _ in range(n_prod)]      # one private list per thread: no sharing
    consumed = [[] for _ in range(n_cons)]
    stats = {"max_buffer": 0, "overflow": 0, "underflow": 0,
             "producer_blocks": [0] * n_prod, "consumer_blocks": [0] * n_cons}

    log.patch("capacity", capacity)
    log.patch("buffer", [])
    log.patch("total", total)
    log.patch("produced", 0)
    log.patch("consumed", 0)
    counters = {"produced": 0, "consumed": 0}   # only changed while holding mutex
    for i in range(n_prod):
        log.patch(f"producers.P{i + 1}", {"status": "working", "count": 0})
    for i in range(n_cons):
        log.patch(f"consumers.C{i + 1}", {"status": "working", "count": 0})
    log.log("main", "info", f"{n_prod} producers x {per_prod} items = {total} items, "
                            f"{n_cons} consumers, buffer capacity {capacity}")

    def producer(idx: int) -> None:
        name = f"P{idx + 1}"
        try:
            for n in range(per_prod):
                item = f"{name}-{n + 1}"
                log.patch(f"producers.{name}.status", "working")
                if not log.pause(produce_time):
                    return
                if not empty.try_wait():                       # would block => buffer is full
                    stats["producer_blocks"][idx] += 1
                    log.patch(f"producers.{name}.status", "blocked")
                    log.log(name, "block", f"buffer FULL - {name} blocks on empty.wait()")
                    empty.wait()                               # sleeps until a consumer signals
                log.patch(f"producers.{name}.status", "active")
                mutex.wait()
                buffer.append(item)                            # --- critical section ---
                size = len(buffer)
                stats["max_buffer"] = max(stats["max_buffer"], size)
                if size > capacity:
                    stats["overflow"] += 1
                counters["produced"] += 1
                log.patch("buffer", list(buffer))
                log.patch("produced", counters["produced"])
                mutex.signal()                                 # --- end critical section ---
                full.signal()
                produced[idx].append(item)
                log.patch(f"producers.{name}.count", len(produced[idx]))
                log.log(name, "produce", f"produced {item}  (buffer {size}/{capacity})")
            log.patch(f"producers.{name}.status", "done")
        except SemaphoreAborted:
            log.patch(f"producers.{name}.status", "aborted")

    def consumer(idx: int, quota: int) -> None:
        name = f"C{idx + 1}"
        try:
            for _ in range(quota):
                log.patch(f"consumers.{name}.status", "working")
                if not full.try_wait():                        # would block => buffer is empty
                    stats["consumer_blocks"][idx] += 1
                    log.patch(f"consumers.{name}.status", "blocked")
                    log.log(name, "block", f"buffer EMPTY - {name} blocks on full.wait()")
                    full.wait()
                log.patch(f"consumers.{name}.status", "active")
                mutex.wait()
                if not buffer:
                    stats["underflow"] += 1
                    mutex.signal()
                    continue
                item = buffer.popleft()                        # --- critical section ---
                size = len(buffer)
                counters["consumed"] += 1
                log.patch("buffer", list(buffer))
                log.patch("consumed", counters["consumed"])
                mutex.signal()                                 # --- end critical section ---
                empty.signal()
                consumed[idx].append(item)
                log.patch(f"consumers.{name}.count", len(consumed[idx]))
                log.log(name, "consume", f"consumed {item}  (buffer {size}/{capacity})")
                if not log.pause(consume_time):
                    return
            log.patch(f"consumers.{name}.status", "done")
        except SemaphoreAborted:
            log.patch(f"consumers.{name}.status", "aborted")

    quotas = [total // n_cons + (1 if i < total % n_cons else 0) for i in range(n_cons)]
    threads = [threading.Thread(target=producer, args=(i,), daemon=True, name=f"P{i + 1}")
               for i in range(n_prod)]
    threads += [threading.Thread(target=consumer, args=(i, quotas[i]), daemon=True, name=f"C{i + 1}")
                for i in range(n_cons)]
    for t in threads:
        t.start()

    watchdog = 30 + total * (produce_time + consume_time) * 2     # generous overall deadline
    stuck = join_threads(threads, watchdog)
    deadlock = bool(stuck) and not log.cancelled
    if stuck:                                                     # watchdog: tear everything down
        log.log("watchdog", "deadlock", f"{len(stuck)} thread(s) still blocked after "
                                        f"{watchdog:.0f}s - aborting")
        log.cancel()
        join_threads(stuck, 5)

    # ---------- verification ----------
    all_produced = [x for lst in produced for x in lst]
    all_consumed = [x for lst in consumed for x in lst]
    result.stats = {
        "items_planned": total, "items_produced": len(all_produced),
        "items_consumed": len(all_consumed), "max_buffer_size": stats["max_buffer"],
        "capacity": capacity, "producer_blocks": sum(stats["producer_blocks"]),
        "consumer_blocks": sum(stats["consumer_blocks"]),
    }
    result.add("No deadlock - all threads finished", not stuck,
               "all finished" if not stuck else f"{len(stuck)} thread(s) stuck")
    result.add("Buffer never exceeded its capacity",
               stats["overflow"] == 0 and stats["max_buffer"] <= capacity,
               f"max size {stats['max_buffer']} <= capacity {capacity}")
    result.add("Consumers never found an empty buffer after full.wait()", stats["underflow"] == 0)
    result.add("Every produced item was consumed",
               sorted(all_produced) == sorted(all_consumed) and len(all_consumed) == total,
               f"{len(all_consumed)} consumed / {total} produced")
    result.add("No item consumed twice", len(set(all_consumed)) == len(all_consumed))
    result.add("Buffer empty at the end", len(buffer) == 0)
    result.add("Semaphores back to initial values",
               (empty.value, full.value, mutex.value) == (capacity, 0, 1) or log.cancelled,
               f"empty={empty.value} (={capacity}), full={full.value} (=0), mutex={mutex.value} (=1)")
    result.add("Producers blocked on a full buffer", True,
               f"{result.stats['producer_blocks']} time(s)", info=True)
    result.add("Consumers blocked on an empty buffer", True,
               f"{result.stats['consumer_blocks']} time(s)", info=True)
    return result.finalize(started, deadlock=deadlock, cancelled=log.cancelled)
