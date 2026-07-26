"""Paper execution against live bars.

The paper broker uses the same contract as the backtester — a strategy sees a
bar only once it has closed, and its orders fill at the next bar's open through
the same ``ExecutionModel``. That is deliberate: identical fill assumptions mean
any gap between the backtest and the paper record comes from the data, not from
two different simulators disagreeing.

**The paper record starts when the service does.** On its first cycle the broker
adopts the newest closed bar as its starting point and places no trades, so it
never back-fills a track record over history it was not actually running for. A
forward paper record that begins today is small and honest; one that quietly
includes yesterday is neither.

Nothing here reaches an exchange. Positions, cash, and fills are numbers in a
file. There is no account behind them, and the fills are what the fill model
says would have happened, not what a venue confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..backtest.engine import BarContext, Portfolio, Strategy
from ..backtest.execution import ExecutionModel, Order
from ..data.types import Bar, as_of
from ..journal.models import Fill

STATE_FILE = "paper_state.json"
FILLS_FILE = "paper_fills.jsonl"
EQUITY_FILE = "paper_equity.jsonl"


def _order_to_dict(order: Order) -> dict:
    return {
        "symbol": order.symbol,
        "side": order.side,
        "qty": order.qty,
        "setup": order.setup,
        "timeframe": order.timeframe,
        "risk_per_unit": order.risk_per_unit,
    }


def _order_from_dict(row: dict) -> Order:
    return Order(**row)


def fill_to_dict(fill: Fill) -> dict:
    return {
        "ts": fill.ts.isoformat(),
        "symbol": fill.symbol,
        "side": fill.side,
        "qty": fill.qty,
        "price": fill.price,
        "fee": fill.fee,
        "setup": fill.setup,
        "timeframe": fill.timeframe,
        "risk_per_unit": fill.risk_per_unit,
    }


def fill_from_dict(row: dict) -> Fill:
    return Fill(
        ts=datetime.fromisoformat(row["ts"]),
        symbol=row["symbol"],
        side=row["side"],
        qty=row["qty"],
        price=row["price"],
        fee=row["fee"],
        setup=row["setup"],
        timeframe=row["timeframe"],
        risk_per_unit=row["risk_per_unit"],
    )


@dataclass
class PaperState:
    """Everything the broker must remember between cycles."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    pending: list[dict] = field(default_factory=list)
    last_ts: str | None = None
    started_at: str | None = None
    marks: dict[str, float] = field(default_factory=dict)
    """Last known price per symbol. Persisted so that a symbol whose fetch fails
    this cycle keeps its previous mark instead of being valued at zero, which
    would put a false cliff in the paper equity curve."""

    def to_dict(self) -> dict:
        return {
            "cash": self.cash,
            "positions": self.positions,
            "pending": self.pending,
            "last_ts": self.last_ts,
            "started_at": self.started_at,
            "marks": self.marks,
        }

    @classmethod
    def from_dict(cls, row: dict) -> "PaperState":
        return cls(
            cash=row["cash"],
            positions=row.get("positions", {}),
            pending=row.get("pending", []),
            last_ts=row.get("last_ts"),
            started_at=row.get("started_at"),
            marks=row.get("marks", {}),
        )


@dataclass(frozen=True)
class PaperCycle:
    """What one call to ``advance`` did."""

    bars_processed: int
    fills: list[Fill]
    equity: float
    bootstrapped: bool
    """True on the first cycle, when the broker adopted a starting point and
    deliberately placed no trades."""


class PaperBroker:
    """Simulated execution driven by live bars, persisted across restarts."""

    def __init__(self, state: PaperState, execution: ExecutionModel) -> None:
        self.state = state
        self.execution = execution

    def advance(
        self, bars_by_symbol: dict[str, list[Bar]], strategy: Strategy
    ) -> PaperCycle:
        """Process every bar that closed since the last cycle."""
        portfolio = Portfolio(
            cash=self.state.cash,
            positions=dict(self.state.positions),
            marks=dict(self.state.marks),
        )
        for symbol, bars in bars_by_symbol.items():
            if bars:
                portfolio.marks[symbol] = bars[-1].close

        by_ts: dict[datetime, dict[str, Bar]] = {}
        cutoff = datetime.fromisoformat(self.state.last_ts) if self.state.last_ts else None
        for symbol, bars in bars_by_symbol.items():
            for bar in bars:
                if cutoff is None or bar.ts > cutoff:
                    by_ts.setdefault(bar.ts, {})[symbol] = bar
        timeline = sorted(by_ts)

        if cutoff is None:
            # First cycle: adopt a starting point, trade nothing.
            if timeline:
                self.state.last_ts = timeline[-1].isoformat()
            self.state.started_at = datetime.now(timezone.utc).isoformat()
            self.state.cash = portfolio.cash
            self.state.marks = dict(portfolio.marks)
            return PaperCycle(
                bars_processed=0,
                fills=[],
                equity=portfolio.equity(),
                bootstrapped=True,
            )

        pending = [_order_from_dict(row) for row in self.state.pending]
        fills: list[Fill] = []

        for ts in timeline:
            todays = by_ts[ts]

            for order in pending:
                bar = todays.get(order.symbol)
                if bar is None:
                    continue
                price = self.execution.fill_price(order.side, bar.open)
                fill = Fill(
                    ts=ts,
                    symbol=order.symbol,
                    side=order.side,
                    qty=order.qty,
                    price=price,
                    fee=self.execution.fee(price, order.qty),
                    setup=order.setup,
                    timeframe=order.timeframe,
                    risk_per_unit=order.risk_per_unit,
                )
                portfolio.apply(fill)
                fills.append(fill)
            pending = []

            for symbol, bar in todays.items():
                portfolio.marks[symbol] = bar.close

            for symbol in sorted(todays):
                ctx = BarContext(
                    ts=ts,
                    symbol=symbol,
                    history=as_of(bars_by_symbol[symbol], ts),
                    portfolio=portfolio,
                )
                pending.extend(strategy.on_bar(ctx))

            self.state.last_ts = ts.isoformat()

        self.state.cash = portfolio.cash
        self.state.positions = {
            sym: qty for sym, qty in portfolio.positions.items() if qty != 0
        }
        self.state.pending = [_order_to_dict(o) for o in pending]
        self.state.marks = dict(portfolio.marks)

        return PaperCycle(
            bars_processed=len(timeline),
            fills=fills,
            equity=portfolio.equity(),
            bootstrapped=False,
        )
