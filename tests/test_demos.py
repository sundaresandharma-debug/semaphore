"""
Integration tests: every demonstration must verify its own invariants.

The demos are run in "fast mode" (tiny pauses) so the whole file takes a few
seconds.  Each demo returns a DemoResult whose checks are the real assertions
(buffer never over capacity, no fork shared, writers exclusive, ...).
"""

from __future__ import annotations

import time
import unittest

from demos import dining_philosophers, producer_consumer, race_condition, readers_writers
from src.synchronization import DemoResult, EventLog, resolve_params


def failed_checks(result: DemoResult) -> list:
    return [f"{c.name}: {c.detail}" for c in result.checks if not c.ok and not c.info]


class TestDemos(unittest.TestCase):

    def assertDemoPassed(self, result: DemoResult) -> None:
        self.assertEqual(result.status, "PASS", f"failed checks: {failed_checks(result)}")

    def test_race_condition_protected_counter_is_exact(self):
        """The semaphore-protected counter equals threads x increments."""
        r = race_condition.run(log=EventLog(), threads=4, increments=3000, unsync_runs=1)
        self.assertDemoPassed(r)
        self.assertEqual(r.stats["protected_result"], 4 * 3000)

    def test_race_condition_unprotected_counter_never_exceeds_expected(self):
        """Without protection updates can only be lost, never invented."""
        r = race_condition.run(log=EventLog(), threads=4, increments=3000, unsync_runs=2)
        for value in r.stats["unprotected_results"]:
            self.assertLessEqual(value, 4 * 3000)

    def test_producer_consumer_default(self):
        """Producer-Consumer: capacity respected, every item consumed exactly once, no deadlock."""
        r = producer_consumer.run(log=EventLog())
        self.assertDemoPassed(r)
        self.assertLessEqual(r.stats["max_buffer_size"], r.stats["capacity"])
        self.assertEqual(r.stats["items_produced"], r.stats["items_consumed"])

    def test_producer_consumer_uneven_quotas_and_capacity_one(self):
        """Capacity 1 and items that do not divide evenly among consumers still terminate."""
        r = producer_consumer.run(log=EventLog(), producers=3, consumers=2, items=7, capacity=1)
        self.assertDemoPassed(r)
        self.assertEqual(r.stats["items_consumed"], 21)

    def test_producer_consumer_blocking_really_happens(self):
        """Slow consumers + tiny buffer: producers must have blocked on a full buffer."""
        r = producer_consumer.run(log=EventLog(), producers=3, consumers=1, items=6,
                                  capacity=2, produce_time=0.0, consume_time=0.01)
        self.assertDemoPassed(r)
        self.assertGreater(r.stats["producer_blocks"], 0)

    def test_readers_writers_default(self):
        """Readers-Writers: no violations, no torn reads, all operations completed."""
        r = readers_writers.run(log=EventLog())
        self.assertDemoPassed(r)
        self.assertEqual(r.stats["violations"], 0)

    def test_readers_writers_readers_overlap(self):
        """Longer reads: several readers are inside at the same time."""
        r = readers_writers.run(log=EventLog(), readers=5, writers=1, rounds=2,
                                read_time=0.05, write_time=0.01, idle_time=0.0)
        self.assertDemoPassed(r)
        self.assertGreaterEqual(r.stats["max_concurrent_readers"], 2)

    def test_dining_philosophers_with_room_completes(self):
        """With the room semaphore every philosopher eats all meals, no deadlock."""
        r = dining_philosophers.run(log=EventLog(), meals=5)
        self.assertDemoPassed(r)
        self.assertEqual(r.stats["meals_eaten"], [5] * 5)

    def test_dining_philosophers_deadlock_is_detected_without_room(self):
        """Without the room the table deadlocks and the watchdog reports it (no hang)."""
        started = time.monotonic()
        r = dining_philosophers.run(log=EventLog(), use_room=False, watchdog=0.5, meals=2)
        self.assertEqual(r.status, "DEADLOCK")
        self.assertEqual(r.stats["meals_eaten"], [0] * 5, "nobody can eat once all five hold a left fork")
        self.assertLess(time.monotonic() - started, 5, "the watchdog must end the run promptly")

    def test_cancel_stops_a_running_demo(self):
        """log.cancel() aborts the semaphores and the demo returns CANCELLED promptly."""
        import threading
        log = EventLog()
        timer = threading.Timer(0.15, log.cancel)
        timer.start()
        r = producer_consumer.run(log=log, items=40, produce_time=0.05, consume_time=0.05)
        timer.cancel()
        self.assertEqual(r.status, "CANCELLED")

    def test_parameters_are_clamped_and_validated(self):
        """Out-of-range or garbage parameters fall back to safe values."""
        p = resolve_params(producer_consumer.PARAMS, {"producers": 999, "items": "abc", "capacity": -4})
        self.assertEqual(p["producers"], 6)
        self.assertEqual(p["capacity"], 1)
        self.assertEqual(p["items"], 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
