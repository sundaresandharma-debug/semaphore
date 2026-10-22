"""The synchronization demonstration: the Dining Philosophers problem."""

from . import dining_philosophers

ALL_DEMOS = [dining_philosophers]
DEMOS_BY_ID = {demo.ID: demo for demo in ALL_DEMOS}

__all__ = ["ALL_DEMOS", "DEMOS_BY_ID", "dining_philosophers"]
