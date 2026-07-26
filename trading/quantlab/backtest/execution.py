"""Order and fill modelling for the backtester.

Orders are market orders submitted on a bar close and filled at the NEXT bar's
open. That one-bar delay is the whole point: a strategy that decides on a
close it can see, and trades at a price that has not printed yet, cannot peek.

The fill model is deliberately pessimistic and deliberately crude. Real slippage
depends on order size relative to book depth, time of day, and whether you are
trading with or against the flow. A flat basis-point haircut captures none of
that. It is a floor on realistic costs, not an estimate of yours.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Order:
    """A market order to be filled on the next bar's open."""

    symbol: str
    side: Side
    qty: float
    setup: str = "unspecified"
    timeframe: str = "unspecified"
    risk_per_unit: float | None = None


@dataclass(frozen=True)
class ExecutionModel:
    """Flat fee and slippage assumptions.

    Attributes:
        fee_bps: Commission in basis points of notional, charged per fill.
        slippage_bps: Price concession in basis points, applied against the
            trader — buys fill above the open, sells fill below it.
    """

    fee_bps: float = 5.0
    slippage_bps: float = 5.0

    def fill_price(self, side: Side, reference_price: float) -> float:
        """Apply slippage to the reference (next-bar open) price."""
        slip = reference_price * self.slippage_bps / 10_000.0
        return reference_price + slip if side == "buy" else reference_price - slip

    def fee(self, price: float, qty: float) -> float:
        """Commission charged on a fill of ``qty`` at ``price``."""
        return abs(price * qty) * self.fee_bps / 10_000.0
