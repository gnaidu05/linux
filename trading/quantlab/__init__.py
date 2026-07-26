"""quantlab — a local trading-research toolkit.

Five composable modules: a rules-based scanner, an event-driven backtester, a
realized-trade journal, a news aggregator, and an advisory alert layer.

What this package deliberately does not contain: any price forecast, any
probability of profit, any directional call, and any code that can reach a
broker or exchange. Simulation is the only execution path that exists here.
See ``LIMITATIONS.md`` for what each number can and cannot support.
"""

__all__ = ["alerts", "backtest", "data", "indicators", "journal", "news", "scanner"]
