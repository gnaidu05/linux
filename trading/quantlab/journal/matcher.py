"""Match fills into closed round trips, FIFO.

Fills are matched oldest-open-lot first. A fill that reduces an existing
position closes lots; a fill that adds to it, or that flips through zero, opens
new ones. Fees are allocated to a closed trade pro-rata by quantity from both
the entry lot and the closing fill.

Quantity still open at the end is reported separately and never folded into
realized statistics.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .models import ClosedTrade, Fill


@dataclass
class _Lot:
    ts: datetime
    price: float
    qty: float
    remaining: float
    fee: float
    setup: str
    timeframe: str
    risk_per_unit: float | None


@dataclass(frozen=True)
class OpenPosition:
    """Quantity still held after all fills were processed."""

    symbol: str
    direction: Literal["long", "short"]
    qty: float
    avg_price: float


@dataclass(frozen=True)
class MatchResult:
    closed: list[ClosedTrade]
    open_positions: list[OpenPosition]


def match_fills(fills: list[Fill]) -> MatchResult:
    """Turn a fill history into closed trades plus whatever is still open."""
    by_symbol: dict[str, deque[_Lot]] = defaultdict(deque)
    direction: dict[str, Literal["long", "short"]] = {}
    closed: list[ClosedTrade] = []

    for fill in sorted(fills, key=lambda f: f.ts):
        lots = by_symbol[fill.symbol]
        signed = fill.qty if fill.side == "buy" else -fill.qty
        open_dir = direction.get(fill.symbol)
        incoming_dir: Literal["long", "short"] = "long" if signed > 0 else "short"
        qty_left = abs(signed)
        fee_per_unit = fill.fee / fill.qty if fill.qty else 0.0

        # Close against opposing lots first.
        if lots and open_dir is not None and open_dir != incoming_dir:
            while qty_left > 0 and lots:
                lot = lots[0]
                matched = min(qty_left, lot.remaining)
                entry_fee = (lot.fee / lot.qty) * matched if lot.qty else 0.0
                closed.append(
                    ClosedTrade(
                        symbol=fill.symbol,
                        direction=open_dir,
                        qty=matched,
                        entry_ts=lot.ts,
                        entry_price=lot.price,
                        exit_ts=fill.ts,
                        exit_price=fill.price,
                        fees=entry_fee + fee_per_unit * matched,
                        setup=lot.setup,
                        timeframe=lot.timeframe,
                        risk_per_unit=lot.risk_per_unit,
                    )
                )
                lot.remaining -= matched
                qty_left -= matched
                if lot.remaining <= 1e-12:
                    lots.popleft()
            if not lots:
                direction.pop(fill.symbol, None)

        # Anything left opens (or extends) a position in the fill's direction.
        if qty_left > 1e-12:
            lots.append(
                _Lot(
                    ts=fill.ts,
                    price=fill.price,
                    qty=qty_left,
                    remaining=qty_left,
                    fee=fee_per_unit * qty_left,
                    setup=fill.setup,
                    timeframe=fill.timeframe,
                    risk_per_unit=fill.risk_per_unit,
                )
            )
            direction[fill.symbol] = incoming_dir

    open_positions = []
    for symbol, lots in sorted(by_symbol.items()):
        remaining = [lot for lot in lots if lot.remaining > 1e-12]
        if not remaining:
            continue
        qty = sum(lot.remaining for lot in remaining)
        avg = sum(lot.price * lot.remaining for lot in remaining) / qty
        open_positions.append(
            OpenPosition(
                symbol=symbol,
                direction=direction[symbol],
                qty=qty,
                avg_price=avg,
            )
        )

    closed.sort(key=lambda t: (t.exit_ts, t.symbol))
    return MatchResult(closed=closed, open_positions=open_positions)
