"""Core market data types.

A ``Bar`` is a completed OHLCV candle. ``ts`` is the bar's CLOSE time: the
moment the bar became fully known. Every module in this package relies on that
convention to avoid look-ahead, so do not populate ``ts`` with an open time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Bar:
    """One completed OHLCV candle.

    Attributes:
        symbol: Instrument identifier, e.g. ``"BTC-USD"``.
        ts: Bar close time (timezone-aware UTC by convention).
        open, high, low, close: Prices in the instrument's quote currency.
        volume: Traded volume over the bar.
    """

    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def as_of(bars: list[Bar], ts: datetime) -> list[Bar]:
    """Return only the bars that had already closed at or before ``ts``.

    This is the point-in-time gate: anything that screens or backtests should
    slice history through this function rather than indexing raw lists, so a
    future bar can never leak into a decision made at ``ts``.
    """
    return [b for b in bars if b.ts <= ts]
