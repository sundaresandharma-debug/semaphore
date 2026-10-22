# Semaphore Implementation from Scratch for Process Synchronization

An Operating Systems project: a counting semaphore and a binary semaphore written
from scratch in Python (built only on `threading.Lock` and `threading.Event`),
used to solve the **Dining Philosophers problem**, with a command-line menu and a
browser interface.

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
```

If `python` is not recognised on Windows, use the Python launcher instead: `py server.py`, `py main.py`.

## 1. Problem statement

Concurrent threads that share data can interleave their instructions in any order.
Without coordination this produces **race conditions** (lost updates), two threads
using the same resource at once, and **deadlock** (everyone waits for someone else
forever). The Dining Philosophers problem is the classic example of deadlock: five
philosophers share five forks, each needs two forks to eat, and if all five pick up
their left fork at once, nobody can ever eat. The operating system needs a
primitive that lets threads **wait without wasting CPU** and be **woken exactly when
they may continue**. That primitive is the semaphore (Dijkstra, 1965).

## 2. Objectives

1. Implement counting and binary semaphores from scratch, without Python's built-in semaphores.
2. Guarantee mutual exclusion, no lost wake-ups, no busy-waiting, and FIFO fairness.
3. Solve the Dining Philosophers problem with the custom semaphore and prevent deadlock with a room semaphore.
4. Detect deadlock instead of hanging.
5. Have the demonstration verify its own results and report PASS, FAIL or DEADLOCK.

## 3. Operating Systems concepts covered

Counting semaphores, binary semaphores, mutual exclusion, critical sections, atomic
operations, blocking and waking threads (no busy-waiting), FIFO queues and fairness,
the dining philosophers problem, the four conditions for deadlock
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
│   ├── catalog.py            GET  /api/catalog     the demonstration and its settings
│   ├── playground.py         POST /api/playground  replay wait()/signal() clicks on a real Semaphore
│   └── run.py                POST /api/run         run a demo to completion
├── public/
│   ├── index.html            the browser interface (plain HTML, CSS and JavaScript, no libraries)
│   ├── app.js, styles.css    its script and styles
│   ├── 404.html              page-not-found page
│   └── favicon.svg, theme.js
├── docs/                     LAUNCH_CHECKLIST.md (accessibility, security, quality)
├── src/
│   ├── __init__.py
│   ├── semaphore.py          Semaphore and BinarySemaphore (the heart of the project)
│   └── synchronization.py    shared helpers: EventLog, DemoResult, join_threads (watchdog), parameters
├── demos/
│   ├── __init__.py
│   └── dining_philosophers.py  the Dining Philosophers demonstration
├── main.py                   command-line entry point (interactive menu)
├── server.py                 run the web interface locally (same API as Vercel)
├── webcore.py                the web API: shared by api/*.py and server.py
├── vercel.json               Vercel settings (static site in public/, Python functions in api/)
├── README.md
├── VIVA.md                   viva questions and presentation outline
└── requirements.txt
```

Layers: `semaphore.py` knows nothing about the demonstration. The demonstration uses only the semaphore and
`synchronization.py`. `main.py` and the web interface are two front-ends for the same demonstration.
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
* **`abort()`.** Wakes every blocked thread with `SemaphoreAborted`. Used by the watchdog and when a run is cancelled, so that no thread can ever be left sleeping forever.
* **Other API:** `value` and `waiting` (read-only properties), `try_wait()`, context-manager support (`with sem:`), `ValueError`/`TypeError` for invalid arguments.

## 7. The Dining Philosophers demonstration

`demos/dining_philosophers.py` uses the custom semaphores, verifies its own claims and reports `PASS`, `FAIL` or `DEADLOCK`.

Five philosophers sit at a round table with one fork between each pair, so there are five forks, each a `BinarySemaphore(1)`. A philosopher thinks, picks up the left fork, then the right fork, eats, and puts both down.

Deadlock needs all four Coffman conditions:

* **Mutual exclusion:** a fork is a binary semaphore, so only one philosopher can hold it.
* **Hold and wait:** a philosopher keeps the left fork while waiting for the right one.
* **No pre-emption:** a fork cannot be taken away from the philosopher holding it.
* **Circular wait:** philosopher 0 waits for 1, 1 waits for 2, and so on back to 0.

A `room = Semaphore(4)` lets at most four philosophers compete for forks at once. With four philosophers and five forks, at least one of them can always pick up both forks, so the circular wait can never close and deadlock is impossible.

Every blocking wait has a timeout (the watchdog). Switch the room off and all five pick up their left fork and wait for the right one; the watchdog reports `DEADLOCK`, and each philosopher puts down its fork and stops instead of hanging.

Verified: no fork held by two philosophers, everyone eats with both forks, everyone completes all meals, all forks free at the end, room semaphore back to 4.

## 8. Running the project

### Browser version (recommended for the demonstration)

```bash
python server.py
```

The terminal prints `Open: http://localhost:8000` and your browser opens by itself. If it does not, open that address manually. Press **Ctrl+C** in the terminal to stop. Options: `--port 9000` (another port; if 8000 is busy the next free port is used automatically) and `--no-browser`.

Pages: **Overview** (**Run both versions** runs the demonstration with and without the room semaphore), **Dining philosophers** (change the settings, press Run, watch the table and the semaphores, see the verification checklist), and the **Playground** (operate a real semaphore by hand).

On the Dining philosophers page: **Run** uses your settings, **Quick run** uses fast settings and shows the result in a second or two, **Reset to defaults** restores the settings, and an estimate of the run time appears under the settings (with a warning if the run would pass the 50-second server limit). After a run you can change the **replay speed** (0.25× to 4×) and press **Replay again** to watch the same run without running it again. The **Theme** button in the sidebar switches between automatic, light and dark colours.

The server listens on this computer only (`127.0.0.1`), accepts only JSON requests and serves only a fixed list of project files.

The status of every launch item (accessibility, security, quality) is in
[`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md).

### Deploy on Vercel

The project is ready for Vercel as is (no build step, no packages):

1. Push this folder to a GitHub repository.
2. On vercel.com choose **Add New > Project**, import the repository and press **Deploy**.
   Leave the framework preset as **Other**; `vercel.json` already sets everything.

Or from a terminal with the Vercel CLI: `npx vercel --prod`.

`public/index.html` is served as the site, and each file in `api/` becomes a Python
function. A run is limited to 50 seconds (the functions allow 60).

### Terminal version

```bash
python main.py                  # interactive menu 0-3
python main.py --all            # with and without the room semaphore, exit code 0 if both behave as expected
python main.py --demo 1         # with the room semaphore (expected: PASS)
python main.py --demo 2         # without the room semaphore (expected: DEADLOCK)
```

### In Antigravity, VS Code or any editor

Open the project folder in the editor, open its integrated terminal, and run `python server.py`. Then open `http://localhost:8000` in a browser. If your editor offers an embedded browser or port forwarding, the same address works there.

### Do not double-click `public/index.html`

The page needs the Python backend to run the semaphores. Opened as a plain file it shows a message telling you to start `python server.py`.

## 9. Actual output

Everything in this section was **captured from real runs** while this project was built (Linux, Python 3.13). Timings and the unprotected counter values will be different on your computer; that is expected.

With the room semaphore, `python main.py --demo 1 --quiet`:

```text
============================================================
  Dining Philosophers: With the room semaphore
============================================================
  Five philosophers need two forks each. Forks are binary semaphores; a 'room' semaphore admits at most four philosophers at a time, which makes deadlock impossible. Switch the room off to see all five deadlock.
  Expected result: PASS


  --- Verification ----------------------------------------
  [ok  ] The table never deadlocked  (watchdog stayed silent)
  [ok  ] No fork was ever held by two philosophers at once  (0 violations)
  [ok  ] Every philosopher ate with both forks
  [ok  ] Every philosopher completed all required meals  (meals eaten: [3, 3, 3, 3, 3])
  [ok  ] All forks free at the end
  [ok  ] Room semaphore back to 4  (value 4)

  --- Statistics ------------------------------------------
  meals_eaten                  [3, 3, 3, 3, 3]
  meals_required               3
  room_semaphore               True
  fork_violations              0

  RESULT: PASS   (0.02s)
```

Without the room semaphore, `python main.py --demo 2 --quiet` (watchdog 3 seconds):

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

  RESULT: DEADLOCK   (3.10s)
```

Both versions, `python main.py --all --quiet`:

```text
  FINAL SUMMARY
============================================================
  Version                       Result      Expected        Time
  --------------------------------------------------------------
  With the room semaphore       PASS        PASS           0.02s
  Without the room semaphore    DEADLOCK    DEADLOCK       3.10s
  --------------------------------------------------------------
  Both versions behaved as expected.

  Total time: 3.1s
```

The terminal menu looks like this (literal layout, not captured output):

```text
========================================
   SEMAPHORE SYNCHRONIZATION PROJECT
       Dining Philosophers Problem
========================================

1. With the room semaphore (deadlock prevented)
2. Without the room semaphore (deadlock detected)
3. Run both
0. Exit

Enter your choice:
```

## 10. Threads versus processes

Python **threads** inside one program **share memory**, and this semaphore coordinates exactly such threads: its counter and queue are ordinary Python objects protected by a `threading.Lock`.

Separate operating-system **processes** do **not** share memory. A `Semaphore` object created in one process is a different object in another process, so **this implementation does not synchronize separate processes**. To coordinate processes you need an inter-process mechanism: for example `multiprocessing.Semaphore`, named semaphores or shared memory provided by the OS, or file or socket based locks. The *ideas* in this project (counter, queue, hand-off, the Dining Philosophers solution) carry over unchanged; the storage and the lock underneath would have to live in shared OS memory.

A note on the GIL: CPython's global interpreter lock lets only one thread run Python bytecode at a time, but it can switch threads **between** the bytecodes of `counter += 1`. The GIL therefore does not make shared data safe, and real synchronization is still needed.

## 11. Known limitations

* **Threads, not processes** (see section 10).
* **Python-level semaphore.** It is built from `Lock` and `Event`, which themselves rely on the operating system. A kernel semaphore (futex-based) is faster; this project optimises for clarity and correctness.
* **Demo pauses are simulated work.** Thinking and eating use short sleeps to model time passing. They are never used to make synchronization correct.
* **One prevention strategy.** The room semaphore lets at most four philosophers sit down, so a philosopher may wait for a seat even when both of its forks are free.
* **Not run on Windows** by the author of this build (see section 4).
* **The browser replays a sampled recording.** Each run is executed to completion on the server while the state is sampled every 0.1 s, then animated in the browser. Very short states between two samples may not be visible, and the animation starts only after the run has finished.

## 12. Future enhancements

* A multi-process version using `multiprocessing` shared memory with OS-level semaphores, to compare with the thread version.
* Other ways to prevent deadlock at the table, such as numbering the forks and always picking up the lower-numbered fork first, compared with the room semaphore.
* Condition variables and monitors as an alternative to semaphores, compared side by side.
* Priority inheritance, and a demonstration of priority inversion.
* Deadlock detection using a resource-allocation graph, and the banker's algorithm for avoidance.
* Streaming updates to the browser (server-sent events or WebSockets) so the animation starts while the threads are still running.
