"""
Entry point of the Semaphore Synchronization Project (command-line version).

    python main.py              interactive menu
    python main.py --all        run all four demos, exit code 0 if all pass
    python main.py --demo 2     run one demo (1-4)

For the browser version run:  python server.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List

from demos import ALL_DEMOS
from src.synchronization import DemoResult, EventLog

ROOT = Path(__file__).resolve().parent

MENU = """
========================================
   SEMAPHORE SYNCHRONIZATION PROJECT
========================================

1. Race Condition
2. Producer-Consumer
3. Readers-Writers
4. Dining Philosophers
5. Run All Demonstrations
0. Exit
"""

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


def run_demo(index: int, quiet: bool = False) -> DemoResult:
    demo = ALL_DEMOS[index]
    banner(f"Demo {index + 1}: {demo.TITLE}")
    print(f"  {demo.DESCRIPTION}\n")
    result = demo.run(log=EventLog(echo=not quiet))
    print_result(result)
    return result


def run_all(quiet: bool = False) -> List[DemoResult]:
    results = [run_demo(i, quiet=quiet) for i in range(len(ALL_DEMOS))]
    banner("FINAL SUMMARY")
    print(f"  {'Demonstration':<24}{'Result':<12}{'Time':>8}")
    print("  " + "-" * 44)
    for demo, res in zip(ALL_DEMOS, results):
        print(f"  {demo.TITLE:<24}{res.status:<12}{res.duration:>7.2f}s")
    passed = sum(r.passed for r in results)
    print("  " + "-" * 44)
    print(f"  {passed} of {len(results)} demonstrations passed.")
    return results


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
        if choice in ("1", "2", "3", "4"):
            run_demo(int(choice) - 1)
        elif choice == "5":
            run_all()
        else:
            print(f"\n  '{choice}' is not a valid choice - please enter 0-5.")
            continue
        try:
            input("\nPress Enter to return to the menu...")
        except (EOFError, KeyboardInterrupt):
            return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Semaphore synchronization project")
    parser.add_argument("--all", action="store_true", help="run all demos non-interactively")
    parser.add_argument("--demo", type=int, choices=[1, 2, 3, 4], help="run one demo")
    parser.add_argument("--quiet", action="store_true", help="hide the live event lines")
    args = parser.parse_args(argv)

    started = time.monotonic()
    if args.all:
        ok = all(r.passed for r in run_all(quiet=args.quiet))
        print(f"\n  Total time: {time.monotonic() - started:.1f}s")
        return 0 if ok else 1
    if args.demo:
        return 0 if run_demo(args.demo - 1, quiet=args.quiet).passed else 1
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
