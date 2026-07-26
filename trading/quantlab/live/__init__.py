"""Live data and continuous paper operation.

This subpackage adds two things to the toolkit: a read-only public market data
feed, and a supervised loop that runs the scanner, a paper-traded strategy, the
journal, and the alert rules on a schedule.

"Live" here means live *data* and *continuous operation*. It does not mean live
execution. There is no broker client, no exchange account, no credential, and no
order-routing code path in this subpackage or anywhere else in the package —
``tests/test_safety.py`` asserts it against every source file.

The entry point is ``python -m quantlab.live.service``. That module is
deliberately not imported here: importing it from the package ``__init__`` makes
``runpy`` load it twice and warn.
"""

from .config import ServiceConfig
from .feed import FeedError, fetch_bars, fetch_universe, parse_candles
from .paper import PaperBroker, PaperCycle, PaperState
from .runner import CycleResult, run_cycle
from .store import Store

__all__ = [
    "CycleResult",
    "FeedError",
    "PaperBroker",
    "PaperCycle",
    "PaperState",
    "ServiceConfig",
    "Store",
    "fetch_bars",
    "fetch_universe",
    "parse_candles",
    "run_cycle",
]
