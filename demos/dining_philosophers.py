"""
Demo 4 - Dining Philosophers (5 philosophers, 5 forks).

Philosopher i sits between fork i (left) and fork (i+1) % 5 (right) and needs
BOTH to eat.  Every fork is a BinarySemaphore(1).

THE DEADLOCK
    If every philosopher grabs the left fork first, all five can each hold one
    fork and wait forever for the right one.  Four conditions hold at once:
    mutual exclusion, hold-and-wait, no pre-emption, circular wait.

THE FIX USED HERE: a "room" semaphore
    room = Semaphore(4): at most FOUR philosophers may try to pick up forks at
    the same time.  With 5 forks and at most 4 philosophers competing, the
    circular wait can never close (by pigeonhole at least one of the four can
    always get both forks), so deadlock is impossible.
    Turn the room off (``use_room=False``) to watch the deadlock happen.

WATCHDOG
    Every blocking wait uses ``wait(timeout=watchdog)``. If a philosopher waits
    longer than that, a deadlock is reported, held forks are released and the
    thread exits - the program never hangs.
"""

from __future__ import annotations

import random
import threading
import time

from src.semaphore import BinarySemaphore, Semaphore, SemaphoreAborted
from src.synchronization import DemoResult, EventLog, join_threads, resolve_params

ID = "dining_philosophers"
TITLE = "Dining Philosophers"
DESCRIPTION = ("Five philosophers need two forks each. Forks are binary semaphores; a 'room' "
               "semaphore admits at most four philosophers at a time, which makes deadlock "
               "impossible. Switch the room off to see all five deadlock.")
WATCH_FOR = [
    "A philosopher eats only while holding BOTH neighbouring forks.",
    "With the room semaphore (value 4) the table never deadlocks and everyone finishes all meals.",
    "Without the room, all five grab their left fork, wait for the right one, and the watchdog reports DEADLOCK.",
]
N = 5
PARAMS = [
    {"name": "meals", "label": "Meals per philosopher", "type": "int", "min": 1, "max": 10, "default": 3, "ui": 3},
    {"name": "think_time", "label": "Thinking time (s)", "type": "float", "min": 0.0, "max": 1.0,
     "default": 0.002, "ui": 0.5},
    {"name": "eat_time", "label": "Eating time (s)", "type": "float", "min": 0.0, "max": 0.8,
     "default": 0.002, "ui": 0.5},
    {"name": "pick_time", "label": "Pause between the two forks (s)", "type": "float", "min": 0.0, "max": 0.5,
     "default": 0.0, "ui": 0.1},
    {"name": "use_room", "label": "Use room semaphore (deadlock prevention)", "type": "bool",
     "min": 0, "max": 1, "default": True, "ui": True},
    {"name": "watchdog", "label": "Deadlock watchdog (s)", "type": "float", "min": 0.3, "max": 20.0,
     "default": 5.0, "ui": 3.0},
]


class _Deadlock(Exception):
    pass


def run(log: EventLog | None = None, **params) -> DemoResult:
    log = log or EventLog()
    p = resolve_params(PARAMS, params)
    meals, think_time, eat_time = p["meals"], p["think_time"], p["eat_time"]
    use_room, watchdog = p["use_room"], p["watchdog"]
    # Without the room, make the deadlock certain: everybody is hungry at once and
    # pauses a moment between the two forks, so all five hold their left fork first.
    pick_time = p["pick_time"] if use_room else max(p["pick_time"], 0.1)
    started = time.monotonic()
    result = DemoResult(TITLE)

    forks = [BinarySemaphore(1, name=f"fork{i}", tracer=log.tracer) for i in range(N)]
    room = Semaphore(N - 1, name="room", tracer=log.tracer)
    gate = Semaphore(0, name="start-gate")
    log.watch_semaphores(**{f"fork{i}": f for i, f in enumerate(forks)})
    if use_room:
        log.watch_semaphores(room=room)

    obs_lock = threading.Lock()                         # observer only
    holder = [None] * N                                 # who holds each fork right now
    meals_eaten = [0] * N
    violations: list = []
    deadlock_flag = threading.Event()
    log.patch("use_room", use_room)
    log.patch("room_size", N - 1)
    log.patch("deadlock", False)
    for i in range(N):
        log.patch(f"phil.{i}", {"status": "thinking", "meals": 0})
        log.patch(f"forks.{i}", None)
    log.log("main", "info", f"{N} philosophers, {meals} meals each, "
                            f"room semaphore {'ON (4 seats)' if use_room else 'OFF - expect deadlock'}")

    def philosopher(i: int) -> None:
        name = f"Phil {i}"
        left, right = i, (i + 1) % N
        held: list = []                                 # forks this thread currently holds
        in_room = False
        rng = random.Random(i)

        def take_fork(f: int) -> None:
            if not forks[f].try_wait():
                who = holder[f]
                log.log(name, "block", f"{name} waits for fork {f}"
                                       + (f" (held by Phil {who})" if who is not None else ""))
                log.patch(f"phil.{i}.status", "waiting")
                if not forks[f].wait(timeout=watchdog):
                    raise _Deadlock(f"{name} waited more than {watchdog:g}s for fork {f} "
                                    f"while holding {held or 'nothing'}")
            with obs_lock:
                if holder[f] is not None:
                    violations.append(f"fork {f} taken by Phil {i} while held by Phil {holder[f]}")
                holder[f] = i
                held.append(f)
                log.patch(f"forks.{f}", i)
            if deadlock_flag.is_set():                  # the table is already declared dead:
                raise _Deadlock("stopped after deadlock was declared")   # do not carry on eating
            log.log(name, "acquire", f"{name} picked up fork {f}")

        def drop_fork(f: int) -> None:
            with obs_lock:
                holder[f] = None
                log.patch(f"forks.{f}", None)
            held.remove(f)
            forks[f].signal()

        try:
            gate.wait()
            for meal in range(meals):
                if deadlock_flag.is_set():
                    raise _Deadlock("stopped after deadlock was declared")
                log.patch(f"phil.{i}.status", "thinking")
                if use_room and not log.pause(think_time * rng.uniform(0.5, 1.5)):
                    return
                if not use_room and meal > 0 and not log.pause(think_time * rng.uniform(0.5, 1.5)):
                    return
                log.patch(f"phil.{i}.status", "hungry")
                log.log(name, "hungry", f"{name} is hungry (meal {meal + 1}/{meals})")

                if use_room:
                    if not room.try_wait():
                        log.log(name, "block", f"{name} waits outside the room (4 already inside)")
                        log.patch(f"phil.{i}.status", "waiting")
                        if not room.wait(timeout=watchdog):
                            raise _Deadlock(f"{name} waited more than {watchdog:g}s for the room")
                    in_room = True

                take_fork(left)
                log.patch(f"phil.{i}.status", "hungry")
                if not log.pause(pick_time):
                    return
                take_fork(right)

                # ------------- EATING: must hold both forks -------------
                with obs_lock:
                    if holder[left] != i or holder[right] != i:
                        violations.append(f"Phil {i} eating without both forks")
                log.patch(f"phil.{i}.status", "eating")
                log.log(name, "eat", f"{name} EATING with forks {left} and {right}")
                if not log.pause(eat_time):
                    return
                meals_eaten[i] += 1
                log.patch(f"phil.{i}.meals", meals_eaten[i])
                # --------------------------------------------------------

                drop_fork(left)
                drop_fork(right)
                if in_room:
                    room.signal()
                    in_room = False
                log.log(name, "release", f"{name} finished meal {meal + 1}, put both forks down")
            log.patch(f"phil.{i}.status", "done")
        except _Deadlock as exc:
            if not deadlock_flag.is_set():
                deadlock_flag.set()
                log.patch("deadlock", True)
                log.log("watchdog", "deadlock", f"DEADLOCK DETECTED: {exc}")
            log.patch(f"phil.{i}.status", "deadlocked")
            for f in list(held):
                drop_fork(f)
            if in_room:
                room.signal()
        except SemaphoreAborted:
            log.patch(f"phil.{i}.status", "aborted")

    threads = [threading.Thread(target=philosopher, args=(i,), daemon=True, name=f"Phil{i}")
               for i in range(N)]
    for t in threads:
        t.start()
    for _ in threads:
        gate.signal()

    budget = watchdog * 2 + meals * (think_time * 1.5 + eat_time + pick_time) * N * 3 + 10
    stuck = join_threads(threads, budget)
    if stuck:                                           # should not happen: every wait has a timeout
        log.log("watchdog", "deadlock", "threads still running after the overall deadline - aborting")
        deadlock_flag.set()
        log.cancel()
        join_threads(stuck, 5)

    # ---------- verification ----------
    deadlocked = deadlock_flag.is_set()
    result.stats = {"meals_eaten": list(meals_eaten), "meals_required": meals,
                    "room_semaphore": use_room, "fork_violations": len(violations)}
    result.add("The table never deadlocked", not deadlocked,
               "watchdog stayed silent" if not deadlocked
               else "WATCHDOG: every philosopher is blocked holding one fork")
    result.add("No fork was ever held by two philosophers at once", not violations,
               "0 violations" if not violations else violations[0])
    result.add("Every philosopher ate with both forks", not violations)
    result.add("Every philosopher completed all required meals",
               all(m == meals for m in meals_eaten), f"meals eaten: {meals_eaten}")
    result.add("All forks free at the end", all(f.value == 1 for f in forks) or log.cancelled)
    if use_room:
        result.add("Room semaphore back to 4", room.value == N - 1 or log.cancelled, f"value {room.value}")
    else:
        result.notes.append("The room semaphore was switched OFF on purpose to demonstrate deadlock.")
    return result.finalize(started, deadlock=deadlocked, cancelled=log.cancelled and not deadlocked)
