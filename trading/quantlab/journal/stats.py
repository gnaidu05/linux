"""Statistics over realized trading history.

Everything here describes trades that actually closed. Nothing is annualized,
extrapolated, or projected forward, because a sample of your own closed trades
is small, non-stationary, and selected by decisions you were making at the time.

Two limits worth keeping in mind while reading any output of this module:

* Expectancy is a sample mean. With 30 trades its standard error is large enough
  that a positive number is routinely consistent with a zero-edge process. The
  ``n`` beside every breakdown is there so you notice when a cell is thin.
* Breakdowns by setup or timeframe slice an already small sample into smaller
  ones. The best-looking cell in a breakdown is the one most likely to be noise.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .matcher import MatchResult, match_fills
from .models import ClosedTrade, Fill


@dataclass(frozen=True)
class Stats:
    """Realized performance over a set of closed trades."""

    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    """Total of losing trades' net P&L, as a positive number."""
    net_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float | None
    """``None`` when there were no losses — a ratio with a zero denominator is
    not infinity, it is unmeasured."""
    expectancy: float
    """Mean net P&L per trade, in quote currency."""
    max_drawdown: float
    """Deepest peak-to-trough decline of the cumulative realized P&L curve, in
    quote currency. Trade-sequence drawdown, not mark-to-market drawdown: it
    does not see open-position pain between entries and exits."""
    n_trades_with_r: int
    expectancy_r: float | None
    """Mean R-multiple, over the ``n_trades_with_r`` trades that recorded an
    initial stop. ``None`` when no trade did."""
    avg_win_r: float | None
    avg_loss_r: float | None

    def report(self) -> str:
        pf = "n/a (no losses)" if self.profit_factor is None else f"{self.profit_factor:.2f}"
        lines = [
            f"trades              {self.n_trades} ({self.n_wins}W / {self.n_losses}L)",
            f"win rate            {self.win_rate:.1%}",
            f"net P&L             {self.net_pnl:+,.2f}",
            f"expectancy/trade    {self.expectancy:+,.2f}",
            f"avg win / avg loss  {self.avg_win:+,.2f} / {self.avg_loss:+,.2f}",
            f"profit factor       {pf}",
            f"max drawdown        {self.max_drawdown:,.2f} (closed-trade sequence)",
        ]
        if self.expectancy_r is None:
            lines.append(
                f"expectancy in R     n/a (0 of {self.n_trades} trades recorded an initial stop)"
            )
        else:
            lines.append(
                f"expectancy in R     {self.expectancy_r:+.2f}R "
                f"over {self.n_trades_with_r} of {self.n_trades} trades"
            )
        return "\n".join(lines)


def compute_stats(trades: list[ClosedTrade]) -> Stats:
    """Summarize a list of closed trades."""
    if not trades:
        return Stats(
            n_trades=0, n_wins=0, n_losses=0, win_rate=0.0, gross_profit=0.0,
            gross_loss=0.0, net_pnl=0.0, avg_win=0.0, avg_loss=0.0,
            profit_factor=None, expectancy=0.0, max_drawdown=0.0,
            n_trades_with_r=0, expectancy_r=None, avg_win_r=None, avg_loss_r=None,
        )

    pnls = [t.net_pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)

    equity = 0.0
    peak = 0.0
    worst = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        worst = max(worst, peak - equity)

    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    win_rs = [r for r in rs if r > 0]
    loss_rs = [r for r in rs if r <= 0]

    return Stats(
        n_trades=len(trades),
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=len(wins) / len(trades),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=sum(pnls),
        avg_win=sum(wins) / len(wins) if wins else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else None,
        expectancy=sum(pnls) / len(pnls),
        max_drawdown=worst,
        n_trades_with_r=len(rs),
        expectancy_r=(sum(rs) / len(rs)) if rs else None,
        avg_win_r=(sum(win_rs) / len(win_rs)) if win_rs else None,
        avg_loss_r=(sum(loss_rs) / len(loss_rs)) if loss_rs else None,
    )


def breakdown(trades: list[ClosedTrade], key: str) -> dict[str, Stats]:
    """Group trades by ``"setup"``, ``"timeframe"``, or ``"symbol"`` and score each."""
    groups: dict[str, list[ClosedTrade]] = defaultdict(list)
    for t in trades:
        groups[getattr(t, key)].append(t)
    return {name: compute_stats(group) for name, group in sorted(groups.items())}


@dataclass(frozen=True)
class JournalReport:
    """Full journal output for one fill history."""

    overall: Stats
    by_setup: dict[str, Stats]
    by_timeframe: dict[str, Stats]
    by_symbol: dict[str, Stats]
    match: MatchResult

    def report(self) -> str:
        lines = ["REALIZED TRADING HISTORY (closed trades only)", self.overall.report()]
        if self.match.open_positions:
            lines.append("")
            lines.append(
                f"{len(self.match.open_positions)} position(s) still open and excluded "
                "from every statistic above:"
            )
            for p in self.match.open_positions:
                lines.append(f"  {p.symbol} {p.direction} {p.qty:g} @ {p.avg_price:,.4f}")
        for title, table in (
            ("BY SETUP", self.by_setup),
            ("BY TIMEFRAME", self.by_timeframe),
            ("BY SYMBOL", self.by_symbol),
        ):
            lines.extend(["", title])
            for name, s in table.items():
                pf = "n/a" if s.profit_factor is None else f"{s.profit_factor:.2f}"
                lines.append(
                    f"  {name:<16} n={s.n_trades:<4} win={s.win_rate:.0%} "
                    f"net={s.net_pnl:+,.2f} exp={s.expectancy:+,.2f} pf={pf}"
                )
        return "\n".join(lines)


def build_journal(fills: list[Fill]) -> JournalReport:
    """Match a fill history into trades and compute every breakdown."""
    match = match_fills(fills)
    trades = match.closed
    return JournalReport(
        overall=compute_stats(trades),
        by_setup=breakdown(trades, "setup"),
        by_timeframe=breakdown(trades, "timeframe"),
        by_symbol=breakdown(trades, "symbol"),
        match=match,
    )
