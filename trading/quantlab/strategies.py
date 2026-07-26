"""Strategies shared by the demo run and the live paper service.

There is one, and it is deliberately plain. ``DonchianBreakout`` exists because
it is simple enough to verify by hand, not because there is evidence it works.
Nothing in this repository establishes that it has an edge, and the demo run
prints a walk-forward result on synthetic data specifically to show what its
in-sample numbers are worth.
"""

from __future__ import annotations

from .backtest.engine import BarContext
from .backtest.execution import Order
from .indicators import atr, donchian_high, donchian_low


class DonchianBreakout:
    """Long-only channel breakout, sized at a fixed fraction of equity.

    Buys when the close exceeds the prior ``entry_window``-bar high and exits
    when it drops below the prior ``exit_window``-bar low. Both channels exclude
    the current bar, so the entry test is a genuine breakout.
    """

    def __init__(
        self,
        entry_window: int = 20,
        exit_window: int = 10,
        equity_fraction: float = 0.2,
        timeframe: str = "1d",
    ):
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.equity_fraction = equity_fraction
        self.timeframe = timeframe

    def on_bar(self, ctx: BarContext) -> list[Order]:
        bars = ctx.history
        if len(bars) < max(self.entry_window, self.exit_window) + 15:
            return []
        close = bars[-1].close
        position = ctx.position()

        if position == 0:
            breakout = donchian_high(bars, self.entry_window, exclude_current=True)[-1]
            if close > breakout:
                stop_distance = atr(bars, 14)[-1] * 2.0
                qty = (ctx.portfolio.equity() * self.equity_fraction) / close
                return [
                    Order(
                        symbol=ctx.symbol,
                        side="buy",
                        qty=qty,
                        setup=f"donchian_{self.entry_window}",
                        timeframe=self.timeframe,
                        risk_per_unit=stop_distance,
                    )
                ]
            return []

        exit_level = donchian_low(bars, self.exit_window, exclude_current=True)[-1]
        if close < exit_level:
            return [
                Order(
                    symbol=ctx.symbol,
                    side="sell",
                    qty=position,
                    setup=f"donchian_{self.entry_window}",
                    timeframe=self.timeframe,
                )
            ]
        return []
