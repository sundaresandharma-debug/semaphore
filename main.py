"""
Entry point of the Semaphore Synchronization Project (command-line version).

    python main.py              interactive menu
    python main.py --all        run the Dining Philosophers with and without the room semaphore
    python main.py --demo 1     with the room semaphore (should PASS)
    python main.py --demo 2     without the room semaphore (should report DEADLOCK)

For the browser version run:  python server.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

from demos import dining_philosophers as demo
from src.synchronization import DemoResult, EventLog

ROOT = Path(__file__).resolve().parent

MENU = """
========================================
   SEMAPHORE SYNCHRONIZATION PROJECT
       Dining Philosophers Problem
========================================

1. With the room semaphore (deadlock prevented)
2. Without the room semaphore (deadlock detected)
3. Run both
0. Exit
"""

# The two versions: label, parameters, and the result each one should give.
VERSIONS = [
    ("With the room semaphore", {"use_room": True}, "PASS"),
    # The pause between the two forks makes all five philosophers hold their left fork at once.
    ("Without the room semaphore", {"use_room": False, "pick_time": 0.1, "watchdog": 3.0}, "DEADLOCK"),
]

ICON = {"PASS": "PASS", "FAIL": "FAIL", "DEADLOCK": "DEADLOCK", "CANCELLED": "CANCELLED"}


def banner(text: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_result(result: DemoResult) -> None:
    print("\n  --- Verification " + "-" * 40)
    for check in result.checks:
        mark = "info" if check.info else ("ok  " if check.ok else "FAIL")
        detail = f"  ({check.detail})" if check.detail else ""
        print(f"  [{mark}] {check.name}{detail}")
    print("\n  --- Statistics " + "-" * 42)
    for key, value in result.stats.items():
        print(f"  {key:<28} {value}")
    for note in result.notes:
        print(f"  note: {note}")
    print(f"\n  RESULT: {ICON.get(result.status, result.status)}   ({result.duration:.2f}s)")


def run_version(index: int, quiet: bool = False) -> DemoResult:
    label, params, expected = VERSIONS[index]
    banner(f"{demo.TITLE}: {label}")
    print(f"  {demo.DESCRIPTION}\n  Expected result: {expected}\n")
    result = demo.run(log=EventLog(echo=not quiet), **params)
    print_result(result)
    return result


def as_expected(index: int, result: DemoResult) -> bool:
    return result.status == VERSIONS[index][2]


def run_all(quiet: bool = False) -> bool:
    results = [run_version(i, quiet=quiet) for i in range(len(VERSIONS))]
    banner("FINAL SUMMARY")
    print(f"  {'Version':<30}{'Result':<12}{'Expected':<12}{'Time':>8}")
    print("  " + "-" * 62)
    for (label, _, expected), res in zip(VERSIONS, results):
        print(f"  {label:<30}{res.status:<12}{expected:<12}{res.duration:>7.2f}s")
    ok = all(as_expected(i, r) for i, r in enumerate(results))
    print("  " + "-" * 62)
    print("  Both versions behaved as expected." if ok else "  A version did NOT give the expected result.")
    return ok


def interactive() -> int:
    while True:
        print(MENU)
        try:
            choice = input("Enter your choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            return 0
        if choice == "0":
            print("Bye!")
            return 0
        if choice in ("1", "2"):
            run_version(int(choice) - 1)
        elif choice == "3":
            run_all()
        else:
            print(f"\n  '{choice}' is not a valid choice - please enter 0-3.")
            continue
        try:
            input("\nPress Enter to return to the menu...")
        except (EOFError, KeyboardInterrupt):
            return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semaphore synchronization project: Dining Philosophers")
    parser.add_argument("--all", action="store_true", help="run both versions non-interactively")
    parser.add_argument("--demo", type=int, choices=[1, 2], help="1 = with the room semaphore, 2 = without")
    parser.add_argument("--quiet", action="store_true", help="hide the live event lines")
    args = parser.parse_args(argv)

    started = time.monotonic()
    if args.all:
        ok = run_all(quiet=args.quiet)
        print(f"\n  Total time: {time.monotonic() - started:.1f}s")
        return 0 if ok else 1
    if args.demo:
        i = args.demo - 1
        return 0 if as_expected(i, run_version(i, quiet=args.quiet)) else 1
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
