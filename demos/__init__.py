"""The four synchronization demonstrations."""

from . import dining_philosophers, producer_consumer, race_condition, readers_writers

# Order = order in the menu (1-4).
ALL_DEMOS = [race_condition, producer_consumer, readers_writers, dining_philosophers]
DEMOS_BY_ID = {demo.ID: demo for demo in ALL_DEMOS}

__all__ = ["ALL_DEMOS", "DEMOS_BY_ID", "race_condition", "producer_consumer",
           "readers_writers", "dining_philosophers"]
