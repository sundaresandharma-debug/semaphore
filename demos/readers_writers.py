"""
Demo 3 - Readers-Writers (first readers-writers problem: READERS-PREFERENCE).

Rules: many readers may read at the same time, but a writer needs the
resource all to itself.

    mutex = BinarySemaphore(1)   protects the shared variable read_count
    rw    = BinarySemaphore(1)   "the resource": held by ONE writer, or by the
                                 readers as a group

    reader:  mutex.wait()
             read_count += 1
             if read_count == 1: rw.wait()       # first reader locks writers out
             mutex.signal()
             ... READ ...
             mutex.wait()
             read_count -= 1
             if read_count == 0: rw.signal()     # last reader lets writers in
             mutex.signal()

    writer:  rw.wait()  ... WRITE ...  rw.signal()

Priority / starvation: this solution prefers READERS. As long as at least one
reader is inside, new readers walk straight in (read_count > 0, so they skip
rw.wait()) and a waiting writer keeps being overtaken. With a steady stream of
overlapping readers a writer can STARVE. (The "writers-preference" variant
adds one more semaphore to stop new readers once a writer is waiting, but then
readers can starve instead.)  This demo reports the longest time a writer
waited so the effect is visible.

How violations are detected: every reader/writer registers itself in a small
instrumentation block (guarded by a plain lock that is NOT part of the
algorithm under test) and checks the rules; writers also update two fields
non-atomically so a reader that sees a half-finished write is caught too.
"""

from __future__ import annotations

import threading
import time

from src.semaphore import BinarySemaphore, Semaphore, SemaphoreAborted
from src.synchronization import DemoResult, EventLog, join_threads, resolve_params

ID = "readers_writers"
TITLE = "Readers-Writers"
DESCRIPTION = ("Many readers may read together, but a writer needs exclusive access. "
               "A binary 'rw' semaphore guards the resource and a binary 'mutex' guards "
               "the shared reader count (readers-preference solution).")
WATCH_FOR = [
    "Several readers can be inside at once (max concurrent readers > 1).",
    "A writer is always alone: no reader and no other writer overlaps it.",
    "Readers never see a half-written value (the two fields a and b always match).",
    "Readers-preference: a writer can be overtaken again and again - starvation is possible.",
]
PARAMS = [
    {"name": "readers", "label": "Readers", "type": "int", "min": 1, "max": 8, "default": 4, "ui": 4},
    {"name": "writers", "label": "Writers", "type": "int", "min": 1, "max": 4, "default": 2, "ui": 2},
    {"name": "rounds", "label": "Operations per thread", "type": "int", "min": 1, "max": 10, "default": 5, "ui": 3},
    {"name": "read_time", "label": "Read duration (s)", "type": "float", "min": 0.0, "max": 1.0,
     "default": 0.005, "ui": 0.4},
    {"name": "write_time", "label": "Write duration (s)", "type": "float", "min": 0.0, "max": 1.0,
     "default": 0.005, "ui": 0.5},
    {"name": "idle_time", "label": "Pause between operations (s)", "type": "float", "min": 0.0, "max": 1.0,
     "default": 0.002, "ui": 0.2},
]


def run(log: EventLog | None = None, **params) -> DemoResult:
    log = log or EventLog()
    p = resolve_params(PARAMS, params)
    n_readers, n_writers, rounds = p["readers"], p["writers"], p["rounds"]
    read_time, write_time, idle_time = p["read_time"], p["write_time"], p["idle_time"]
    started = time.monotonic()
    result = DemoResult(TITLE)

    mutex = BinarySemaphore(1, name="mutex", tracer=log.tracer)    # guards read_count
    rw = BinarySemaphore(1, name="rw", tracer=log.tracer)          # guards the resource
    gate = Semaphore(0, name="start-gate")                         # start line: all threads go together
    log.watch_semaphores(mutex=mutex, rw=rw)

    shared = {"read_count": 0}                                     # only touched while holding mutex
    data = {"a": 0, "b": 0, "version": 0}                          # the protected resource

    # --- instrumentation (observer only; not part of the algorithm) -----
    obs_lock = threading.Lock()
    obs = {"readers": 0, "writers": 0, "max_readers": 0, "violations": [], "torn": 0,
           "reads": 0, "writes": 0, "writer_wait_max": 0.0}

    def violation(msg: str) -> None:
        obs["violations"].append(msg)
        log.log("CHECK", "violation", msg)
        log.patch("violations", len(obs["violations"]))

    log.watch("read_count", lambda: shared["read_count"])
    log.patch("violations", 0)
    log.patch("active_readers", 0)
    log.patch("active_writers", 0)
    log.patch("data", {"a": 0, "b": 0, "version": 0})
    for i in range(n_readers):
        log.patch(f"readers.R{i + 1}", {"status": "idle", "ops": 0})
    for i in range(n_writers):
        log.patch(f"writers.W{i + 1}", {"status": "idle", "ops": 0})
    log.log("main", "info", f"{n_readers} readers, {n_writers} writers, {rounds} operations each")

    def reader(idx: int) -> None:
        name = f"R{idx + 1}"
        try:
            gate.wait()
            for _ in range(rounds):
                if not log.pause(idle_time):
                    return
                log.patch(f"readers.{name}.status", "waiting")
                mutex.wait()
                shared["read_count"] += 1
                if shared["read_count"] == 1:
                    if not rw.try_wait():
                        log.log(name, "block", f"{name} is first reader but a writer is active - waits on rw")
                        rw.wait()                                  # first reader locks out writers
                mutex.signal()

                # ---------------- READING ----------------
                with obs_lock:
                    obs["readers"] += 1
                    obs["max_readers"] = max(obs["max_readers"], obs["readers"])
                    if obs["writers"] > 0:
                        violation(f"{name} reads while a writer is writing!")
                    log.patch("active_readers", obs["readers"])
                log.patch(f"readers.{name}.status", "reading")
                log.log(name, "read", f"{name} READING   ({obs['readers']} reader(s) inside)")
                a = data["a"]
                log.pause(read_time)
                b = data["b"]
                with obs_lock:
                    obs["readers"] -= 1
                    obs["reads"] += 1
                    if a != b:
                        obs["torn"] += 1
                        violation(f"{name} saw a half-written value (a={a}, b={b})")
                    log.patch("active_readers", obs["readers"])
                # -----------------------------------------

                mutex.wait()
                shared["read_count"] -= 1
                if shared["read_count"] == 0:
                    rw.signal()                                    # last reader lets writers in
                mutex.signal()
                log.patch(f"readers.{name}.ops", log_ops(name))
            log.patch(f"readers.{name}.status", "done")
        except SemaphoreAborted:
            log.patch(f"readers.{name}.status", "aborted")

    def writer(idx: int) -> None:
        name = f"W{idx + 1}"
        try:
            gate.wait()
            for _ in range(rounds):
                if not log.pause(idle_time):
                    return
                log.patch(f"writers.{name}.status", "waiting")
                t_wait = time.monotonic()
                if not rw.try_wait():
                    log.log(name, "block", f"{name} must wait for exclusive access")
                    rw.wait()
                waited = time.monotonic() - t_wait

                # ---------------- WRITING ----------------
                with obs_lock:
                    obs["writers"] += 1
                    obs["writer_wait_max"] = max(obs["writer_wait_max"], waited)
                    if obs["writers"] > 1:
                        violation(f"{name} writes while another writer is writing!")
                    if obs["readers"] > 0:
                        violation(f"{name} writes while {obs['readers']} reader(s) are reading!")
                    log.patch("active_writers", obs["writers"])
                log.patch(f"writers.{name}.status", "writing")
                log.log(name, "write", f"{name} WRITING   (waited {waited:.2f}s)")
                data["version"] += 1
                v = data["version"]
                data["a"] = v                                      # two separate steps: a reader that
                log.pause(write_time)                              # got in now would see a != b
                data["b"] = v
                log.patch("data", dict(data))
                with obs_lock:
                    obs["writers"] -= 1
                    obs["writes"] += 1
                    log.patch("active_writers", obs["writers"])
                # -----------------------------------------

                rw.signal()
                log.patch(f"writers.{name}.ops", log_ops(name))
            log.patch(f"writers.{name}.status", "done")
        except SemaphoreAborted:
            log.patch(f"writers.{name}.status", "aborted")

    ops_done = {}

    def log_ops(name: str) -> int:
        with obs_lock:
            ops_done[name] = ops_done.get(name, 0) + 1
            return ops_done[name]

    threads = [threading.Thread(target=reader, args=(i,), daemon=True, name=f"R{i + 1}")
               for i in range(n_readers)]
    threads += [threading.Thread(target=writer, args=(i,), daemon=True, name=f"W{i + 1}")
                for i in range(n_writers)]
    for t in threads:
        t.start()
    for _ in threads:
        gate.signal()                                              # fire the starting gun

    ops_time = rounds * (read_time + write_time + idle_time) * (n_readers + n_writers)
    watchdog = 30 + ops_time * 2
    stuck = join_threads(threads, watchdog)
    deadlock = bool(stuck) and not log.cancelled
    if stuck:
        log.log("watchdog", "deadlock", f"{len(stuck)} thread(s) stuck after {watchdog:.0f}s - aborting")
        log.cancel()
        join_threads(stuck, 5)

    # ---------- verification ----------
    expected_reads, expected_writes = n_readers * rounds, n_writers * rounds
    result.stats = {
        "reads": obs["reads"], "writes": obs["writes"],
        "max_concurrent_readers": obs["max_readers"],
        "longest_writer_wait_s": round(obs["writer_wait_max"], 3),
        "violations": len(obs["violations"]), "final_version": data["version"],
    }
    result.add("No deadlock - all threads finished", not stuck)
    result.add("No synchronization violations detected", not obs["violations"],
               "0 violations" if not obs["violations"] else f"{len(obs['violations'])}: {obs['violations'][0]}")
    result.add("Writers always had exclusive access (no reader/writer overlap)", not obs["violations"])
    result.add("No reader saw a half-written value", obs["torn"] == 0, f"{obs['torn']} torn read(s)")
    result.add("All reads completed", obs["reads"] == expected_reads, f"{obs['reads']}/{expected_reads}")
    result.add("All writes completed (none lost)",
               obs["writes"] == expected_writes and data["version"] == expected_writes,
               f"{obs['writes']}/{expected_writes}, final version {data['version']}")
    result.add("Reader count back to 0, semaphores back to 1",
               (shared["read_count"], mutex.value, rw.value) == (0, 1, 1) or log.cancelled)
    result.add("Multiple readers shared the resource", True,
               f"max {obs['max_readers']} at once", info=True)
    result.add("Longest time a writer waited", True,
               f"{obs['writer_wait_max']:.2f}s (readers-preference: writers can starve)", info=True)
    result.notes.append("Readers-preference: readers have priority, so writers can starve if "
                        "readers keep arriving.")
    return result.finalize(started, deadlock=deadlock, cancelled=log.cancelled)
