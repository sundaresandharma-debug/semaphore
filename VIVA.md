# Viva preparation

Everything below refers to this project's own code. Open `src/semaphore.py` while you read: the comment block at the top is your cheat sheet.

## Ten viva questions with answers

**1. What is a semaphore, and what do `wait()` and `signal()` do?**
A semaphore is a protected counter plus a queue of sleeping threads. `wait()` (P, down) takes a permit if one is available, otherwise the thread joins the back of the queue and sleeps. `signal()` (V, up) gives a permit back: if someone is queued it is handed straight to the thread at the front, otherwise the counter goes up by one. In my code the counter is `_value`, the queue is `_waiters` (a deque), and a `threading.Lock` makes every change atomic. `value` never goes below zero; the number of sleeping threads is reported separately as `waiting`.

**2. What is the difference between a counting and a binary semaphore, and between a binary semaphore and a mutex?**
A counting semaphore can hold any value from 0 upwards and manages several identical resources (the `empty` slots of the buffer, the 4 seats of the dining room). A binary semaphore is only ever 0 or 1 and gives mutual exclusion (`mutex`, the forks, `rw`). A mutex normally has an *owner*: only the thread that locked it may unlock it. A semaphore has no owner: any thread may call `signal()`, which is why semaphores can also be used for signalling between threads (the start gate in the demos, and the "signal() from outside" button in the Playground). In my `BinarySemaphore`, a `signal()` when the value is already 1 raises `SemaphoreOverflowError`, because a double release would break mutual exclusion.

**3. What is a race condition? Where do you show it?**
A race condition is when the result depends on how threads happen to interleave. `counter += 1` is three steps (READ, ADD, WRITE); if two threads READ the same value, one update is lost. Demo 1 runs the same workload several times without protection (a different wrong total each time) and once with a `BinarySemaphore` around the read-modify-write (the critical section), which always gives exactly threads x increments. The wrong totals vary because the operating system decides when a thread is interrupted.

**4. How does your semaphore avoid busy-waiting and lost wake-ups?**
No busy-waiting: a blocked thread sleeps on its own `threading.Event`; there are no loops and no `sleep` calls inside the semaphore. No lost wake-up: a thread decides to sleep and joins the queue inside the *same* critical section (the same lock hold), so a `signal()` either comes before (and `wait()` finds a permit) or after (and the thread is already queued and is woken). There is no gap between "I will sleep" and "I can be woken". Also, `Event.set()` is remembered, so a signal that arrives before the thread reaches `event.wait()` is not lost.

**5. Why does `signal()` hand the permit directly to the first waiter instead of just incrementing the counter?**
If `signal()` only incremented the counter, a brand-new thread calling `wait()` could grab the permit before the sleeping thread wakes up (barging). The waiter would wake, find nothing, and have to queue again, possibly forever (starvation) and out of order. With direct hand-off the counter stays at 0, a newcomer finds no permit and queues behind, and the permit belongs to the waiter from the instant of `signal()`. That also gives strict FIFO order, which a unit test checks.

**6. In Producer-Consumer, why three semaphores, and why must `empty`/`full` be waited on before `mutex`?**
`empty` counts free slots (producers wait on it), `full` counts filled slots (consumers wait on it), `mutex` lets only one thread touch the buffer at a time. If a producer took `mutex` first and then waited on `empty` while the buffer was full, it would sleep *holding the mutex*; the consumers that would free a slot need that mutex, so nobody can ever continue: deadlock. Waiting on `empty`/`full` first means a thread only enters the critical section when it is guaranteed to finish quickly.

**7. In Readers-Writers, who is favoured? Can a writer starve? How would you fix it?**
Readers are favoured. The first reader takes `rw` (locking writers out) and later readers walk in without touching it, while the last reader releases it. As long as new readers keep arriving before the old ones leave, a waiting writer never gets `rw`: starvation is possible. A fix is an extra "turnstile" semaphore: a waiting writer holds the turnstile, which stops new readers from entering until the writer has had its turn (writers-preference, or a fair version).

**8. Name the four conditions for deadlock. How does the room semaphore prevent it in Dining Philosophers?**
Mutual exclusion, hold-and-wait, no pre-emption, circular wait. If all five philosophers pick up their left fork, each holds one fork and waits for the next: a circular wait. The `room` semaphore (value 4) lets at most four philosophers try to pick up forks at once. With five forks and at most four competitors, at least one of them can always get both forks, eat and release them, so the circle can never close. Other cures: pick up forks in a fixed global order, or let odd and even philosophers start on different sides. My watchdog (every wait has a timeout) *detects* a deadlock if one ever happens, which you can show by switching the room off.

**9. Do threads and processes share memory? Does your semaphore work between processes? What does the GIL change?**
Threads of one process share memory; separate processes do not. My semaphore stores its counter and queue in ordinary Python objects, so it synchronizes *threads* of one program, not separate processes; for processes you would use `multiprocessing.Semaphore`, OS named semaphores, or shared memory. The GIL lets only one thread execute Python bytecode at a time, but it can switch threads between the bytecodes of `counter += 1`, so it does not make that statement safe; Demo 1 proves it.

**10. How did you test it, and how do you know there are no lost wake-ups?**
47 `unittest` tests: initial values, blocking and waking, one signal wakes exactly one thread, no barging, FIFO order, timeouts racing with signals (permits issued = permits received + left over), a 2000-round ping-pong where one lost wake-up would hang the test, mutual exclusion under load, a 150-thread stress test, and the demos' own invariant checks. Tests wait for "blocked" using the semaphore's `waiting` counter instead of guessing with sleeps, every wait has a timeout, and the cleanup aborts all semaphores so a failing test cannot hang. I also injected four deliberate bugs into a copy of the semaphore and the tests caught each one, and I repeated the semaphore tests 25 times with no failure. Tests cannot *prove* the absence of every possible bug; the argument for correctness is the invariants plus the single critical section described in question 4.

### Extra questions examiners like

* **"What if I remove the room semaphore?"** Show it live: untick *Use room semaphore* on the Dining Philosophers page and press Run. All five philosophers pick up their left fork (amber), wait for the right one (red), and after the 3-second watchdog the page shows DEADLOCK.
* **"Is this a real operating-system semaphore?"** No. It is built from a lock and an event, and the OS provides the sleeping and waking underneath. A kernel semaphore (futex) is faster; this one is written to be understood.
* **"Why is the counter never negative?"** Some textbooks let a negative value mean "number of waiting threads". I keep `value` (free permits) and `waiting` (sleeping threads) as two separate facts.
* **"Why does the race demo use a random yield?"** Python only switches threads every few milliseconds and the READ-WRITE gap is nanoseconds wide, so on its own the race would be rare. The demo makes a thread give up the CPU between READ and WRITE with a small random probability to model "the scheduler may interrupt here"; the protected run uses the same interruption and stays exact. Be upfront about this.
* **"What happens if `wait()` times out at the same moment as a `signal()`?"** The timed-out thread takes the lock and checks whether it was already granted a permit; if so it keeps it and returns True, otherwise it removes itself from the queue. A permit is never lost.

## Presentation outline (8 slides, about 10 minutes)

1. **The problem.** Two threads, one counter, wrong answer. Why the operating system needs a synchronization primitive.
2. **What a semaphore is.** A counter plus a queue. The two rules of `wait()` and `signal()` in one sentence each.
3. **My implementation.** Built from `Lock` + `Event` only. State, invariants, direct hand-off, FIFO, no busy-waiting, timeouts, `abort()`. Show the comment block in `src/semaphore.py` (Source code page).
4. **Demo 1: race condition.** Live: different wrong totals without the semaphore, exact total with it.
5. **Demo 2 and 3: Producer-Consumer, Readers-Writers.** Live: red "blocked" threads, the buffer filling, several readers at once, a lone writer, 0 violations. Mention reader preference and starvation.
6. **Demo 4: Dining Philosophers.** Live: success with the room semaphore, then untick it and show the deadlock and the watchdog.
7. **Testing.** 47 tests, 2000-round ping-pong, 150-thread stress, deliberate-bug check, repeated runs. Show the Unit tests page all green.
8. **Limits and future work.** Threads not processes, Python-level (not kernel) semaphore, reader preference. Next steps: multi-process version, fair readers-writers, monitors.

## Live demonstration script (browser version)

Open the Vercel link, or start `python server.py` **before** the evaluation and keep the terminal open.

| Step | Do this | Say this |
| --- | --- | --- |
| 1 | **Overview**, press *Run all four demonstrations* | "One click runs the four demonstrations and the unit tests against the real Python code. Everything is verified automatically." |
| 2 | **Race condition**, Run (a few seconds) | "Left: no semaphore, a different wrong total every run. Right: with a BinarySemaphore, exactly the expected number." |
| 3 | Open `src/semaphore.py` in your editor | "This is the algorithm: lock-protected counter, FIFO queue, one Event per sleeping thread, direct hand-off." |
| 4 | **Producer-consumer**, Run | "Red means blocked. Producers sleep when `empty` reaches 0, consumers when `full` reaches 0. Every item is consumed once." |
| 5 | **Readers-writers**, Run | "Many readers together, but the writer always alone. Zero violations. This version favours readers, so writers can starve." |
| 6 | **Dining philosophers**, Run, then untick the room and Run again | "With the room, nobody deadlocks. Without it, all five hold one fork and wait. The watchdog detects it instead of hanging." |
| 7 | **Playground**: A wait(), B wait(), C wait(), then A signal() | "A holds the permit, B and C queue in order. When A signals, the permit goes straight to B and the counter stays at zero." |
| 8 | **Unit tests**, Run | "47 tests, each with a one-line description of what it verifies." |

If the browser misbehaves, the terminal version shows the same results: `python main.py`, then option 5.

## Before the evaluation

* Run `python -m unittest discover -s tests -v` and `python server.py` once on the computer you will present on.
* If port 8000 is busy, the server picks the next free port and prints the address; use the one printed.
* Increase the browser zoom (Ctrl and +) so the back row can read the gauges.
* Record a screen video of one complete run as a backup.
* Read every file once. Be ready to explain any line, and be honest about the limitations listed in the README. Follow your institution's rules about disclosing AI assistance if the examiner asks.
