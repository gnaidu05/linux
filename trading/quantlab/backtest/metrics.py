"""Performance statistics for an equity curve.

Read the caveats attached to each statistic before quoting one. In particular:

* Sharpe here assumes a zero risk-free rate, computes bar-to-bar simple returns,
  and annualizes by multiplying by the square root of ``periods_per_year``. That
  scaling assumes returns are serially independent and roughly normal. Trading
  returns are usually neither, so the number is optimistic for trend-following
  and pessimistic for mean-reversion. On fewer than a few hundred bars its
  sampling error is large enough that ranking strategies by it is unreliable.
* Maximum drawdown is the worst peak-to-trough decline OBSERVED IN THIS SAMPLE.
  The true worst case is unbounded above it; a longer sample nearly always finds
  a deeper one.
* CAGR is derived from first and last equity only, so it inherits whatever luck
  attached to the sample's start and end dates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .engine import BacktestResult, EquityPoint


@dataclass(frozen=True)
class Metrics:
    """Summary statistics with the assumptions that produced them."""

    n_bars: int
    total_return: float
    cagr: float
    annualized_vol: float
    sharpe: float
    max_drawdown: float
    n_fills: int
    periods_per_year: int

    def report(self) -> str:
        return "\n".join(
            [
                f"bars                {self.n_bars}",
                f"total return        {self.total_return:+.2%}",
                f"CAGR                {self.cagr:+.2%}",
                f"annualized vol      {self.annualized_vol:.2%}",
                f"Sharpe (rf=0)       {self.sharpe:+.2f}",
                f"max drawdown        {self.max_drawdown:.2%}  (worst observed in sample)",
                f"fills               {self.n_fills}",
                f"annualization       {self.periods_per_year} periods/year",
            ]
        )


def equity_returns(curve: list[EquityPoint]) -> list[float]:
    """Bar-to-bar simple returns of the equity curve."""
    return [
        curve[i].equity / curve[i - 1].equity - 1.0
        for i in range(1, len(curve))
        if curve[i - 1].equity != 0
    ]


def max_drawdown(curve: list[EquityPoint]) -> float:
    """Worst peak-to-trough decline in the sample, as a positive fraction."""
    peak = float("-inf")
    worst = 0.0
    for point in curve:
        peak = max(peak, point.equity)
        if peak > 0:
            worst = max(worst, (peak - point.equity) / peak)
    return worst


def compute_metrics(result: BacktestResult, *, periods_per_year: int = 252) -> Metrics:
    """Summarize a backtest run. See the module docstring for the caveats."""
    curve = result.equity_curve
    rets = equity_returns(curve)
    start_equity = curve[0].equity
    end_equity = curve[-1].equity
    total_return = end_equity / start_equity - 1.0

    years = len(curve) / periods_per_year
    if years > 0 and start_equity > 0 and end_equity > 0:
        cagr = (end_equity / start_equity) ** (1.0 / years) - 1.0
    else:
        cagr = 0.0

    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        stdev = math.sqrt(var)
        ann_vol = stdev * math.sqrt(periods_per_year)
        sharpe = (mean / stdev) * math.sqrt(periods_per_year) if stdev > 0 else 0.0
    else:
        ann_vol = 0.0
        sharpe = 0.0

    return Metrics(
        n_bars=len(curve),
        total_return=total_return,
        cagr=cagr,
        annualized_vol=ann_vol,
        sharpe=sharpe,
        max_drawdown=max_drawdown(curve),
        n_fills=len(result.fills),
        periods_per_year=periods_per_year,
    )
