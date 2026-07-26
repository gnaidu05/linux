"""Trade journal records.

``Fill`` is the only input the journal accepts. A fill is something that already
happened: a quantity that traded at a price. Intentions, alerts, and "I would
have taken that" do not belong here, because every statistic downstream claims
to describe realized history and stops being true the moment hypothetical trades
are mixed in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class Fill:
    """One executed fill.

    Attributes:
        ts: Execution time.
        symbol: Instrument identifier.
        side: ``"buy"`` or ``"sell"``.
        qty: Filled quantity, always positive; ``side`` carries the direction.
        price: Fill price, excluding fees.
        fee: Cash fee paid on this fill, in quote currency.
        setup: Free-text name of the setup being traded, for breakdowns.
        timeframe: Free-text timeframe label, for breakdowns.
        risk_per_unit: Distance from entry to the initial stop, per unit, at the
            time of entry. Required for R-multiples, and only meaningful on the
            fill that opened the position. Leave it ``None`` when you did not
            record a stop; the journal will exclude that trade from R statistics
            rather than invent a denominator.
    """

    ts: datetime
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float = 0.0
    setup: str = "unspecified"
    timeframe: str = "unspecified"
    risk_per_unit: float | None = None


@dataclass(frozen=True)
class ClosedTrade:
    """A round trip: an entry lot matched against the exit that closed it."""

    symbol: str
    direction: Literal["long", "short"]
    qty: float
    entry_ts: datetime
    entry_price: float
    exit_ts: datetime
    exit_price: float
    fees: float
    setup: str
    timeframe: str
    risk_per_unit: float | None

    @property
    def gross_pnl(self) -> float:
        sign = 1.0 if self.direction == "long" else -1.0
        return sign * (self.exit_price - self.entry_price) * self.qty

    @property
    def net_pnl(self) -> float:
        """Profit after the fees allocated to this lot."""
        return self.gross_pnl - self.fees

    @property
    def r_multiple(self) -> float | None:
        """Net profit expressed in units of initial risk.

        ``None`` when no stop distance was recorded at entry. It is deliberately
        not defaulted to anything: an R-multiple without a real initial risk is
        a made-up number.
        """
        if self.risk_per_unit is None or self.risk_per_unit <= 0:
            return None
        return self.net_pnl / (self.risk_per_unit * self.qty)
