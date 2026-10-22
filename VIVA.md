# Viva preparation

Everything below refers to this project's own code. Open `src/semaphore.py` while you read: the comment block at the top is your cheat sheet.

## Ten viva questions with answers

**1. What is a semaphore, and what do `wait()` and `signal()` do?**
A semaphore is a protected counter plus a queue of sleeping threads. `wait()` (P, down) takes a permit if one is available, otherwise the thread joins the back of the queue and sleeps. `signal()` (V, up) gives a permit back: if someone is queued it is handed straight to the thread at the front, otherwise the counter goes up by one. In my code the counter is `_value`, the queue is `_waiters` (a deque), and a `threading.Lock` makes every change atomic. `value` never goes below zero; the number of sleeping threads is reported separately as `waiting`.

**2. What is the difference between a counting and a binary semaphore, and between a binary semaphore and a mutex?**
A counting semaphore can hold any value from 0 upwards and manages several identical resources (the 4 seats of the room in Dining Philosophers). A binary semaphore is only ever 0 or 1 and gives mutual exclusion (each fork). A mutex normally has an *owner*: only the thread that locked it may unlock it. A semaphore has no owner: any thread may call `signal()`, which is why semaphores can also be used for signalling between threads (the start gate in the demonstration, and the "signal() from outside" button in the Playground). In my `BinarySemaphore`, a `signal()` when the value is already 1 raises `SemaphoreOverflowError`, because a double release would let two philosophers hold the same fork.

**3. What is the Dining Philosophers problem?**
Five philosophers sit at a round table with one fork between each pair, so there are five forks. A philosopher thinks, then needs both the left and the right fork to eat. If all five pick up their left fork at the same moment, each waits forever for the right fork, which its neighbour holds: a deadlock. The problem is to design a protocol with no deadlock, no fork used by two philosophers at once, and no philosopher starving. In my code each fork is a `BinarySemaphore(1)` and a `room = Semaphore(4)` limits how many philosophers sit down.

**4. How does your semaphore avoid busy-waiting and lost wake-ups?**
No busy-waiting: a blocked thread sleeps on its own `threading.Event`; there are no loops and no `sleep` calls inside the semaphore. No lost wake-up: a thread decides to sleep and joins the queue inside the *same* critical section (the same lock hold), so a `signal()` either comes before (and `wait()` finds a permit) or after (and the thread is already queued and is woken). There is no gap between "I will sleep" and "I can be woken". Also, `Event.set()` is remembered, so a signal that arrives before the thread reaches `event.wait()` is not lost.

**5. Why does `signal()` hand the permit directly to the first waiter instead of just incrementing the counter?**
If `signal()` only incremented the counter, a brand-new thread calling `wait()` could grab the permit before the sleeping thread wakes up (barging). The waiter would wake, find nothing, and have to queue again, possibly forever (starvation) and out of order. With direct hand-off the counter stays at 0, a newcomer finds no permit and queues behind, and the permit belongs to the waiter from the instant of `signal()`. That also gives strict FIFO order, which the Playground shows: the permit always goes to the thread at the front of the queue. At the table, this means a hungry philosopher waiting for a fork gets it in arrival order.

**6. Name the four conditions for deadlock and show each one at the table.**
Mutual exclusion (a fork is a binary semaphore, so only one philosopher can hold it), hold and wait (a philosopher keeps the left fork while waiting for the right one), no pre-emption (nobody can take a fork away from the philosopher holding it), circular wait (philosopher 0 waits for 1, 1 for 2, and so on back to 0). Deadlock needs all four at once, so removing any one prevents it.

**7. How does the room semaphore prevent deadlock?**
It removes circular wait. The `room` semaphore has value 4, so at most four philosophers try to pick up forks at once. With five forks and at most four competitors, at least one of them can always get both forks (pigeonhole principle), eat and release them, so the circle of waiting can never close. Other cures: pick up forks in a fixed global order (always the lower-numbered fork first), or let one philosopher pick up the right fork first.

**8. What is the watchdog, and what happens when you switch the room off?**
Every blocking wait in the demonstration has a timeout, `wait(timeout=watchdog)`. Without the room, all five philosophers pick up their left fork and wait for the right one. After the watchdog time (3 seconds on the website) a wait returns `False`, the demonstration reports DEADLOCK, and each philosopher puts down the fork it holds and stops. The program shows the deadlock instead of hanging. As a last safety net, `join_threads` gives all threads one overall deadline and `abort()` wakes anything still blocked.

**9. Do threads and processes share memory? Does your semaphore work between processes? What does the GIL change?**
Threads of one process share memory; separate processes do not. My semaphore stores its counter and queue in ordinary Python objects, so it synchronizes *threads* of one program, not separate processes; for processes you would use `multiprocessing.Semaphore`, OS named semaphores, or shared memory. The GIL lets only one thread execute Python bytecode at a time, but it can switch threads between bytecodes, so it does not make shared data safe and it does not prevent deadlock: the philosophers deadlock with the GIL just as they would without it.

**10. How do you know it works, and that there are no lost wake-ups?**
The demonstration checks its own results after the threads finish and reports PASS, FAIL or DEADLOCK: no fork may ever be held by two philosophers, every philosopher must eat with both forks and finish all meals, all forks must be free at the end and the room semaphore must be back to 4. Without the room the expected result is DEADLOCK, and the Overview's **Run both versions** checks that both versions give their expected result. For lost wake-ups the argument is structural: a thread joins the queue in the same locked section in which it saw the value 0, and `Event.set()` is remembered, so there is no moment in which a signal can be missed. Checks cannot *prove* the absence of every possible bug; the argument for correctness is the invariants plus the single critical section described in question 4.

### Extra questions examiners like

* **"What if I remove the room semaphore?"** Show it live: untick *Use room semaphore* on the Dining Philosophers page and press Run. All five philosophers pick up their left fork (amber), wait for the right one (red), and after the 3-second watchdog the page shows DEADLOCK.
* **"Why does the version without the room set a pause between the two forks?"** With no pause, one philosopher can often grab both forks before the others start, so the deadlock would appear only sometimes. The pause makes all five hold their left fork at the same time, which shows the deadlock every run. It is simulated work and is never used to make the synchronized version correct.
* **"Is this a real operating-system semaphore?"** No. It is built from a lock and an event, and the OS provides the sleeping and waking underneath. A kernel semaphore (futex) is faster; this one is written to be understood.
* **"Why is the counter never negative?"** Some textbooks let a negative value mean "number of waiting threads". I keep `value` (free permits) and `waiting` (sleeping threads) as two separate facts.
* **"What happens if `wait()` times out at the same moment as a `signal()`?"** The timed-out thread takes the lock and checks whether it was already granted a permit; if so it keeps it and returns True, otherwise it removes itself from the queue. A permit is never lost.

## Presentation outline (7 slides, about 10 minutes)

1. **The problem.** Threads that share resources can deadlock. The Dining Philosophers: five philosophers, five forks, and everyone holding a left fork forever.
2. **What a semaphore is.** A counter plus a queue. The two rules of `wait()` and `signal()` in one sentence each.
3. **My implementation.** Built from `Lock` + `Event` only. State, invariants, direct hand-off, FIFO, no busy-waiting, timeouts, `abort()`. Show the comment block at the top of `src/semaphore.py`.
4. **The solution.** Forks as binary semaphores, the four Coffman conditions, and how `room = Semaphore(4)` breaks circular wait.
5. **Live demonstration.** With the room: everyone eats. Without it: all five hold one fork and the watchdog reports DEADLOCK.
6. **Verification.** The demonstration checks its own conditions and reports PASS, FAIL or DEADLOCK. Show the Verification panel and the Overview after Run both versions.
7. **Limits and future work.** Threads not processes, Python-level (not kernel) semaphore, one prevention strategy. Next steps: multi-process version, fork ordering, monitors.

## Live demonstration script (browser version)

Open the Vercel link, or start `python server.py` **before** the evaluation and keep the terminal open.

| Step | Do this | Say this |
| --- | --- | --- |
| 1 | **Overview**, press *Run both versions* | "One click runs the Dining Philosophers twice against the real Python code: with the room semaphore it passes, without it the watchdog detects the deadlock." |
| 2 | Open `src/semaphore.py` in your editor | "This is the algorithm: lock-protected counter, FIFO queue, one Event per sleeping thread, direct hand-off." |
| 3 | **Dining philosophers**, Run (replay speed 0.5x or 0.25x) | "Green means eating with both forks, red means waiting for a fork. The room lets at most four sit down, so someone can always eat." |
| 4 | Untick *Use room semaphore*, Run again | "Now all five pick up their left fork and wait for the right one: circular wait. The watchdog detects it instead of hanging." |
| 5 | **Playground**: A wait(), B wait(), C wait(), then A signal() | "A holds the permit, B and C queue in order. When A signals, the permit goes straight to B and the counter stays at zero." |

If the browser misbehaves, the terminal version shows the same results: `python main.py`, then option 3.

## Before the evaluation

* Run `python main.py --all` and `python server.py` once on the computer you will present on.
* If port 8000 is busy, the server picks the next free port and prints the address; use the one printed.
* Increase the browser zoom (Ctrl and +) so the back row can read the gauges.
* Record a screen video of one complete run as a backup.
* Read every file once. Be ready to explain any line, and be honest about the limitations listed in the README. Follow your institution's rules about disclosing AI assistance if the examiner asks.
