# Semaphore Implementation from Scratch for Process Synchronization

An Operating Systems project: a counting semaphore and a binary semaphore written
from scratch in Python (built only on `threading.Lock` and `threading.Event`),
used to solve four classic synchronization problems, with a command-line menu, a
browser interface, and an automated test suite.

```
Python 3.9+   |   standard library only   |   no pip install needed
```

## Quick start (Windows)

Open **PowerShell** or **Command Prompt** (or the terminal inside your editor) in the
project folder, the one that contains `main.py`.

```bash
python --version                           # must say 3.9 or newer
python server.py                           # browser version  -> http://localhost:8000
python main.py                             # terminal menu version
python -m unittest discover -s tests -v    # automated tests
```

If `python` is not recognised on Windows, use the Python launcher instead: `py server.py`, `py main.py`, `py -m unittest discover -s tests -v`.

## 1. Problem statement

Concurrent threads that share data can interleave their instructions in any order.
Without coordination this produces **race conditions** (lost updates), broken
invariants (a buffer that overflows, a reader that sees half a write) and
**deadlock** (everyone waits for someone else forever). The operating system needs a
primitive that lets threads **wait without wasting CPU** and be **woken exactly when
they may continue**. That primitive is the semaphore (Dijkstra, 1965).

## 2. Objectives

1. Implement counting and binary semaphores from scratch, without Python's built-in semaphores.
2. Guarantee mutual exclusion, no lost wake-ups, no busy-waiting, and FIFO fairness.
3. Demonstrate a race condition and remove it with a semaphore.
4. Solve Producer-Consumer, Readers-Writers and Dining Philosophers with the custom semaphore.
5. Detect synchronization failures (violations, deadlock) instead of hanging.
6. Prove the behaviour with repeatable automated tests.

## 3. Operating Systems concepts covered

Counting semaphores, binary semaphores, mutual exclusion, critical sections, race
conditions, atomic operations, blocking and waking threads (no busy-waiting), FIFO
queues and fairness, producer-consumer (bounded buffer), readers-writers (reader
preference and starvation), dining philosophers, the four conditions for deadlock
(mutual exclusion, hold-and-wait, no pre-emption, circular wait), deadlock prevention
and detection (room semaphore, watchdog timeout), and the difference between threads
and processes.

## 4. System requirements

* Python **3.9 or newer**. Nothing to install: `requirements.txt` is intentionally empty.
* Any terminal and any editor (VS Code, Antigravity, PyCharm, Notepad). The project does not depend on the editor.
* For the browser version, any modern browser (Chrome, Edge, Firefox).
* Tested with Python 3.9, 3.11, 3.12 and 3.13. All development and testing was done on **Linux**. The code uses only portable standard-library calls and contains no non-ASCII output (safe for the Windows console), but it has **not** been run on Windows by the author of this build.

## 5. Project architecture

```text
my-semaphore-project/
├── api/                      Vercel serverless functions (thin wrappers around webcore.py)
│   ├── catalog.py            GET  /api/catalog     list of demos and their settings
│   ├── playground.py         POST /api/playground  replay wait()/signal() clicks on a real Semaphore
│   ├── run.py                POST /api/run         run a demo (or the unit tests) to completion
│   └── source.py             GET  /api/source      source-code viewer
├── public/
│   └── index.html            the browser interface (plain HTML, CSS and JavaScript, no libraries)
├── src/
│   ├── __init__.py
│   ├── semaphore.py          Semaphore and BinarySemaphore (the heart of the project)
│   └── synchronization.py    shared helpers: EventLog, DemoResult, join_threads (watchdog), parameters
├── demos/
│   ├── __init__.py
│   ├── race_condition.py
│   ├── producer_consumer.py
│   ├── readers_writers.py
│   └── dining_philosophers.py
├── tests/
│   ├── __init__.py
│   ├── test_semaphore.py     36 tests of the semaphore itself
│   └── test_demos.py         11 tests: every demo verifies its own invariants
├── main.py                   command-line entry point (interactive menu)
├── server.py                 run the web interface locally (same API as Vercel)
├── webcore.py                the web API: shared by api/*.py and server.py
├── vercel.json               Vercel settings (static site in public/, Python functions in api/)
├── README.md
├── VIVA.md                   viva questions and presentation outline
└── requirements.txt
```

Layers: `semaphore.py` knows nothing about demos. Demos use only the semaphore and
`synchronization.py`. `main.py` and the web interface are two front-ends for the same demos.
The web page is only a display: all semaphore work happens in Python.

Serverless functions cannot keep threads running between requests, so the web API is
stateless: `/api/run` runs the real demo to completion inside one request and records a
snapshot of the semaphores every 100 ms; the page then replays those snapshots at the
speed they happened. The playground sends its whole list of clicks each time and the
server replays them on a fresh `Semaphore`.

## 6. The semaphore algorithm

### State

| Field | Meaning |
| --- | --- |
| `_value` | permits available right now (never negative) |
| `_waiters` | FIFO queue of blocked threads; each has its own `threading.Event` |
| `_lock` | a `threading.Lock` protecting `_value` and `_waiters` |

### Invariants (true whenever the lock is free)

1. `_value >= 0`
2. `_value > 0` implies the queue is empty (a permit never sits unused while someone waits)
3. each queued thread is woken by exactly one `signal()` (or by `abort()`)
4. permits are conserved: `initial + signals - successful waits = _value`

### Pseudocode

```text
wait():
    lock
        if _value > 0:                  # fast path
            _value -= 1
            unlock; return
        w = new waiter (with its own Event)
        _waiters.append(w)              # join the BACK of the queue
    unlock
    w.event.wait()                      # sleep: no CPU used, lock NOT held
    return                              # woken => the permit is ours

signal():
    lock
        if _waiters is not empty:
            w = _waiters.popleft()      # FRONT of the queue (longest waiter)
            w.event.set()               # hand the permit DIRECTLY to w; _value unchanged
        else:
            _value += 1                 # nobody waiting: store the permit
    unlock
```

### Why this design is correct

* **Atomic state updates.** Every read or change of `_value` and `_waiters` happens while holding `_lock`. The lock is held for a few instructions only and never while sleeping.
* **No lost wake-up.** A thread decides to sleep and joins the queue inside the same critical section. A `signal()` therefore either happens before (and then `wait()` finds a permit) or after (and then the thread is already queued and gets woken). There is no gap in between. `Event.set()` is also remembered, so a signal that arrives before the thread reaches `event.wait()` is not lost.
* **Direct hand-off.** When someone is waiting, `signal()` gives the permit to the first waiter and does **not** increment `_value`. A thread that calls `wait()` at that moment sees `_value == 0` and queues behind. Nobody can overtake ("barge"), which also gives **FIFO fairness**.
* **No busy-waiting.** Blocked threads sleep on an `Event`. There are no polling loops and no `sleep` calls inside the semaphore.
* **Timeouts.** `wait(timeout=t)` returns `False` if time runs out. The timed-out thread removes itself from the queue under the lock, but first checks whether a `signal()` granted it a permit in the meantime (in that case the timeout is ignored). A permit is never lost and never handed to a thread that gave up.
* **`BinarySemaphore`.** Initial value must be 0 or 1. A `signal()` on a free binary semaphore with nobody waiting raises `SemaphoreOverflowError` instead of silently creating a second permit: a double release would break mutual exclusion, so the bug is made loud.
* **`abort()`.** Wakes every blocked thread with `SemaphoreAborted`. Used by the watchdog and by the tests so that no thread can ever be left sleeping forever.
* **Other API:** `value` and `waiting` (read-only properties), `try_wait()`, context-manager support (`with sem:`), `ValueError`/`TypeError` for invalid arguments.

## 7. The four demonstrations

All four use the custom semaphores. Each one verifies its own claims and reports `PASS`, `FAIL` or `DEADLOCK`.

**1. Race condition** (`demos/race_condition.py`). Threads increment a shared counter. `counter += 1` is really READ, ADD, WRITE; if two threads read the same old value, one update is lost. The demo runs the workload unprotected several times (different wrong totals each time) and then once with a `BinarySemaphore` around the read-modify-write (always exactly `threads x increments`).

**2. Producer-Consumer** (`demos/producer_consumer.py`). A bounded buffer with `empty = Semaphore(capacity)`, `full = Semaphore(0)` and `mutex = BinarySemaphore(1)`. Producers block when the buffer is full, consumers when it is empty. Always wait on `empty`/`full` *before* `mutex`, otherwise a thread can sleep while holding the mutex and block everyone. Verified: capacity never exceeded, every item consumed exactly once, buffer empty at the end, semaphores back to their initial values, no deadlock.

**3. Readers-Writers** (`demos/readers_writers.py`). Readers-preference solution: `mutex` protects `read_count`, `rw` protects the resource; the first reader locks writers out and the last reader lets them in. Several readers may read together; a writer is always alone. Violations are detected by observers (overlap checks plus a torn-read check: writers update two fields in two steps, and a reader that saw them differ would be caught). **This solution prefers readers, so writers can starve** if readers keep arriving. The demo reports the longest time a writer waited.

**4. Dining Philosophers** (`demos/dining_philosophers.py`). Five philosophers, five forks (each a `BinarySemaphore`). A `room = Semaphore(4)` lets at most four philosophers compete for forks at once, so the circular wait can never close and deadlock is impossible. Every blocking wait has a timeout (the watchdog). Switch the room off and all five pick up their left fork, wait for the right one, and the watchdog reports `DEADLOCK` instead of hanging. Verified: no fork held by two philosophers, everyone eats with both forks, everyone completes all meals.

## 8. Running the project

### Browser version (recommended for the demonstration)

```bash
python server.py
```

The terminal prints `Open: http://localhost:8000` and your browser opens by itself. If it does not, open that address manually. Press **Ctrl+C** in the terminal to stop. Options: `--port 9000` (another port; if 8000 is busy the next free port is used automatically) and `--no-browser`.

Pages: **Overview** (run all four demos and the tests with one button), one page per demonstration (change the settings, press Run, watch the semaphores, see the verification checklist), **Playground** (operate a real semaphore by hand), **Unit tests**, and **Source code**.

The server listens on this computer only (`127.0.0.1`), accepts only JSON requests and serves only a fixed list of project files.

### Deploy on Vercel

The project is ready for Vercel as is (no build step, no packages):

1. Push this folder to a GitHub repository.
2. On vercel.com choose **Add New → Project**, import the repository and press **Deploy**.
   Leave the framework preset as **Other**; `vercel.json` already sets everything.

Or from a terminal with the Vercel CLI: `npx vercel --prod`.

`public/index.html` is served as the site, and each file in `api/` becomes a Python
function. A demo run is limited to 50 seconds (the functions allow 60).

### Terminal version

```bash
python main.py                  # interactive menu 0-6
python main.py --all            # all demos, exit code 0 if all pass
python main.py --demo 4         # one demo (1-4)
python main.py --tests          # unit tests
```

### In Antigravity, VS Code or any editor

Open the project folder in the editor, open its integrated terminal, and run `python server.py`. Then open `http://localhost:8000` in a browser. If your editor offers an embedded browser or port forwarding, the same address works there.

### Do not double-click `public/index.html`

The page needs the Python backend to run the semaphores. Opened as a plain file it shows a message telling you to start `python server.py`.

## 9. Automated tests

```bash
python -m unittest discover -s tests -v
```

Run it from the project folder (the one containing `main.py`). It runs **47 tests** in about 3 to 4 seconds.

* `tests/test_semaphore.py` (36 tests): initial values, taking available permits, blocking, waking, one signal wakes one thread, no barging, FIFO order, competing threads, no lost wake-ups (2000-round ping-pong), timeouts racing with signals, abort, binary semaphore validation and overflow, context manager, invalid arguments, a shared counter under load (24,000 increments), mutual exclusion, a 150-thread stress test, and a check that `semaphore.py` does not use any built-in semaphore.
* `tests/test_demos.py` (11 tests): each demonstration passes its own verification, blocking really happens, a deadlock is detected without the room semaphore, cancellation works, and parameters are validated.

Every test has a one-line description of the behaviour it verifies (shown with `-v`, and in the **Unit tests** page of the browser version).

**Tests cannot hang.** Waiting for "a thread is blocked" uses the semaphore's own `waiting` counter, not guesses with `sleep`; every wait has a timeout; every worker thread is a daemon thread; and `tearDown` aborts all semaphores (waking any thread still blocked) and then checks that every thread has ended.

**Do the tests catch bugs?** Four deliberate bugs were injected into a copy of `semaphore.py` (wake the newest waiter instead of the oldest, increment the counter as well as waking a waiter, remove the binary overflow check, leave a timed-out waiter in the queue). Each one made tests fail.

## 10. Actual output

Everything in this section was **captured from real runs** while this project was built (Linux, Python 3.13). Timings and the unprotected counter values will be different on your computer; that is expected.

Producer-Consumer, `python main.py --demo 2 --quiet`:

```text
============================================================
  Demo 2: Producer-Consumer
============================================================
  Producers put items into a bounded buffer, consumers take them out. empty/full counting semaphores block producers on a full buffer and consumers on an empty one; a binary mutex protects the buffer itself.


  --- Verification ----------------------------------------
  [ok  ] No deadlock - all threads finished  (all finished)
  [ok  ] Buffer never exceeded its capacity  (max size 4 <= capacity 4)
  [ok  ] Consumers never found an empty buffer after full.wait()
  [ok  ] Every produced item was consumed  (45 consumed / 45 produced)
  [ok  ] No item consumed twice
  [ok  ] Buffer empty at the end
  [ok  ] Semaphores back to initial values  (empty=4 (=4), full=0 (=0), mutex=1 (=1))
  [info] Producers blocked on a full buffer  (29 time(s))
  [info] Consumers blocked on an empty buffer  (21 time(s))

  --- Statistics ------------------------------------------
  items_planned                45
  items_produced               45
  items_consumed               45
  max_buffer_size              4
  capacity                     4
  producer_blocks              29
  consumer_blocks              21

  RESULT: PASS   (0.01s)
```

Dining Philosophers with the room semaphore switched off (watchdog 1 second):

```text
  --- Verification ----------------------------------------
  [FAIL] The table never deadlocked  (WATCHDOG: every philosopher is blocked holding one fork)
  [ok  ] No fork was ever held by two philosophers at once  (0 violations)
  [ok  ] Every philosopher ate with both forks
  [FAIL] Every philosopher completed all required meals  (meals eaten: [0, 0, 0, 0, 0])
  [ok  ] All forks free at the end

  --- Statistics ------------------------------------------
  meals_eaten                  [0, 0, 0, 0, 0]
  meals_required               3
  room_semaphore               False
  fork_violations              0
  note: The room semaphore was switched OFF on purpose to demonstrate deadlock.

  RESULT: DEADLOCK   (1.10s)
```

Race condition, `python main.py --demo 1 --quiet` (note how the unprotected totals differ from run to run):

```text
============================================================
  Demo 1: Race Condition
============================================================
  Several threads increment one shared counter. Without a semaphore, increments are lost and the result changes from run to run. A BinarySemaphore around the critical section makes it exact.


  --- Verification ----------------------------------------
  [ok  ] Protected counter equals threads x increments  (80000 vs expected 80000)
  [ok  ] Protected run lost no updates
  [info] Race observed without the semaphore  (lost 54908 updates in the worst run; results [25664, 25092, 30036])
  [info] Unprotected results differ between runs  ([25092, 25664, 30036])

  --- Statistics ------------------------------------------
  expected                     80000
  unprotected_results          [25664, 25092, 30036]
  unprotected_lost_updates     [54336, 54908, 49964]
  protected_result             80000
  protected_lost_updates       0
  note: The unprotected result varies because the OS scheduler decides when a thread is interrupted between its READ and its WRITE.

  RESULT: PASS   (2.81s)
```

All demonstrations, `python main.py --all --quiet`:

```text
  FINAL SUMMARY
============================================================
  Demonstration           Result          Time
  --------------------------------------------
  Race Condition          PASS           2.18s
  Producer-Consumer       PASS           0.01s
  Readers-Writers         PASS           0.08s
  Dining Philosophers     PASS           0.02s
  --------------------------------------------
  4 of 4 demonstrations passed.

  Total time: 2.3s
```

Unit tests, `python -m unittest discover -s tests`:

```text
----------------------------------------------------------------------
Ran 47 tests in 3.231s

OK
```

The terminal menu looks like this (literal layout, not captured output):

```text
========================================
   SEMAPHORE SYNCHRONIZATION PROJECT
========================================

1. Race Condition
2. Producer-Consumer
3. Readers-Writers
4. Dining Philosophers
5. Run All Demonstrations
6. Run Automated Tests
0. Exit

Enter your choice:
```

## 11. Threads versus processes

Python **threads** inside one program **share memory**, and this semaphore coordinates exactly such threads: its counter and queue are ordinary Python objects protected by a `threading.Lock`.

Separate operating-system **processes** do **not** share memory. A `Semaphore` object created in one process is a different object in another process, so **this implementation does not synchronize separate processes**. To coordinate processes you need an inter-process mechanism: for example `multiprocessing.Semaphore`, named semaphores or shared memory provided by the OS, or file or socket based locks. The *ideas* in this project (counter, queue, hand-off, the classic problems) carry over unchanged; the storage and the lock underneath would have to live in shared OS memory.

A note on the GIL: CPython's global interpreter lock lets only one thread run Python bytecode at a time, but it can switch threads **between** the bytecodes of `counter += 1`. The GIL therefore does not make `counter += 1` safe. The race condition demo shows exactly that.

## 12. Known limitations

* **Threads, not processes** (see section 11).
* **Python-level semaphore.** It is built from `Lock` and `Event`, which themselves rely on the operating system. A kernel semaphore (futex-based) is faster; this project optimises for clarity and correctness.
* **The race window is widened on purpose.** CPython switches threads only every few milliseconds, and the READ-WRITE gap is a few nanoseconds wide, so on its own the race would appear rarely. The race demo therefore makes a thread give up the CPU between its READ and its WRITE with a small random probability (`PREEMPT_CHANCE` in `race_condition.py`). This models "the scheduler may interrupt here". The protected run uses the same interruption and is still exact. The actual numbers of lost updates depend on this setting and on your computer.
* **Demo pauses are simulated work.** Thinking, eating, reading and producing use short sleeps to model time passing. They are never used to make synchronization correct.
* **Readers-Writers prefers readers**, so writers can starve. A writers-preference or fair version is a possible extension.
* **Some tests rely on bounded timing** (timeouts of a few seconds, and short polling of `waiting`). They passed 25 repeated runs, 5 consecutive full runs and 3 runs under heavy CPU load, but an extremely overloaded machine could in theory time out.
* **Not run on Windows** by the author of this build (see section 4).
* **The browser page polls** the server about ten times per second. It shows a faithful sampled view, not every instant, so very short states may not be visible.

## 13. Future enhancements

* A multi-process version using `multiprocessing` shared memory with OS-level semaphores, to compare with the thread version.
* Writers-preference and fair (no starvation) readers-writers locks.
* Condition variables and monitors as an alternative to semaphores, compared side by side.
* Priority inheritance, and a demonstration of priority inversion.
* Deadlock detection using a resource-allocation graph, and the banker's algorithm for avoidance.
* Streaming updates to the browser (server-sent events or WebSockets) instead of polling.
