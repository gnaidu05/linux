"""Event-driven backtester.

The loop advances one timestamp at a time and enforces a single rule that makes
results point-in-time correct:

    A strategy sees bar ``t`` only after it has closed, and any order it places
    is filled at bar ``t+1``'s open.

The strategy is handed a history list that the engine builds up incrementally,
so there is no future data in the object it holds — it cannot index past "now"
even by accident. ``tests/test_no_lookahead.py`` asserts this directly with a
strategy that tries to cheat.

What this engine does NOT model: partial fills, order queue position, borrow
availability or cost for shorts, margin calls, dividends, splits, funding rates,
and market impact that scales with size. Every one of those makes real results
worse than simulated ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..data.types import Bar
from ..journal.models import Fill
from .execution import ExecutionModel, Order


@dataclass
class Portfolio:
    """Cash and signed positions, marked at the latest close."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)

    def position(self, symbol: str) -> float:
        """Signed quantity held: positive long, negative short, 0 flat."""
        return self.positions.get(symbol, 0.0)

    def apply(self, fill: Fill) -> None:
        signed = fill.qty if fill.side == "buy" else -fill.qty
        self.positions[fill.symbol] = self.position(fill.symbol) + signed
        self.cash -= signed * fill.price
        self.cash -= fill.fee

    def equity(self) -> float:
        return self.cash + sum(
            qty * self.marks.get(sym, 0.0) for sym, qty in self.positions.items()
        )


@dataclass(frozen=True)
class BarContext:
    """What a strategy is allowed to see when bar ``ts`` closes."""

    ts: datetime
    symbol: str
    history: list[Bar]
    """Bars for ``symbol`` up to and including the one that just closed."""
    portfolio: Portfolio

    @property
    def bar(self) -> Bar:
        return self.history[-1]

    def position(self) -> float:
        return self.portfolio.position(self.symbol)


class Strategy(Protocol):
    """A rule set that turns closed bars into orders."""

    def on_bar(self, ctx: BarContext) -> list[Order]:
        """Called once per symbol per closed bar. Return orders for next open."""


@dataclass(frozen=True)
class EquityPoint:
    ts: datetime
    equity: float


@dataclass(frozen=True)
class BacktestResult:
    """Raw output of one run. Statistics live in ``metrics.py``."""

    equity_curve: list[EquityPoint]
    fills: list[Fill]
    unfilled_orders: int
    """Orders dropped because the symbol had no bar on the following timestamp."""
    start: datetime
    end: datetime
    initial_cash: float

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1].equity if self.equity_curve else self.initial_cash


def run_backtest(
    bars_by_symbol: dict[str, list[Bar]],
    strategy: Strategy,
    *,
    initial_cash: float = 100_000.0,
    execution: ExecutionModel | None = None,
) -> BacktestResult:
    """Run ``strategy`` over ``bars_by_symbol`` and return the raw run output."""
    execution = execution or ExecutionModel()
    portfolio = Portfolio(cash=initial_cash)

    bars_at: dict[datetime, dict[str, Bar]] = {}
    for symbol, bars in bars_by_symbol.items():
        for bar in bars:
            bars_at.setdefault(bar.ts, {})[symbol] = bar
    timeline = sorted(bars_at)

    history: dict[str, list[Bar]] = {sym: [] for sym in bars_by_symbol}
    pending: list[Order] = []
    fills: list[Fill] = []
    equity_curve: list[EquityPoint] = []
    unfilled = 0

    for ts in timeline:
        todays = bars_at[ts]

        # 1. Fill orders placed on the previous close, at this bar's open.
        for order in pending:
            bar = todays.get(order.symbol)
            if bar is None:
                unfilled += 1
                continue
            price = execution.fill_price(order.side, bar.open)
            fill = Fill(
                ts=ts,
                symbol=order.symbol,
                side=order.side,
                qty=order.qty,
                price=price,
                fee=execution.fee(price, order.qty),
                setup=order.setup,
                timeframe=order.timeframe,
                risk_per_unit=order.risk_per_unit,
            )
            portfolio.apply(fill)
            fills.append(fill)
        pending = []

        # 2. Mark to this bar's close and record equity.
        for symbol, bar in todays.items():
            portfolio.marks[symbol] = bar.close
            history[symbol].append(bar)
        equity_curve.append(EquityPoint(ts=ts, equity=portfolio.equity()))

        # 3. Let the strategy see the closed bars and queue orders for next open.
        for symbol in sorted(todays):
            ctx = BarContext(
                ts=ts,
                symbol=symbol,
                history=list(history[symbol]),
                portfolio=portfolio,
            )
            pending.extend(strategy.on_bar(ctx))

    # Orders queued on the final close have no next bar to fill against.
    unfilled += len(pending)

    return BacktestResult(
        equity_curve=equity_curve,
        fills=fills,
        unfilled_orders=unfilled,
        start=timeline[0],
        end=timeline[-1],
        initial_cash=initial_cash,
    )
