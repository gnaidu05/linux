"""Reproducible end-to-end demonstration run.

Run it with::

    python -m quantlab.demo

Everything below is driven by a fixed seed, so the numbers it prints are the
same on every machine and every run — which is the point. Any statistic quoted
about this toolkit should be traceable to a run like this one.

IMPORTANT: the price series here is SYNTHETIC — a seeded random walk with no
drift and no structure for a strategy to find. Performance measured on it says
whether the machinery works, and nothing whatsoever about whether the strategy
would make money. A profitable-looking result on this data is noise, and that is
exactly what makes it a useful smoke test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .alerts.rules import drawdown_alert, scan_threshold_alerts
from .backtest.engine import run_backtest
from .backtest.execution import ExecutionModel
from .backtest.metrics import compute_metrics
from .backtest.validation import walk_forward
from .data.sources import synthetic_bars
from .data.types import Bar
from .journal.stats import build_journal
from .news.aggregator import aggregate
from .news.models import Headline
from .scanner.criteria import Universe
from .scanner.engine import Scanner
from .strategies import DonchianBreakout

SYMBOLS = {"BTC-USD": 1, "ETH-USD": 2, "SOL-USD": 3, "AAPL": 4, "EURUSD": 5}
N_BARS = 900
EXECUTION = ExecutionModel(fee_bps=5.0, slippage_bps=5.0)


def build_bars() -> dict[str, list[Bar]]:
    return {
        symbol: synthetic_bars(symbol, N_BARS, seed=seed, vol=0.02)
        for symbol, seed in SYMBOLS.items()
    }


def _banner(text: str) -> str:
    return f"\n{'=' * 72}\n{text}\n{'=' * 72}"


def main() -> None:
    bars_by_symbol = build_bars()

    print(_banner("0. DATA"))
    print(
        f"{len(bars_by_symbol)} symbols x {N_BARS} synthetic daily bars, fixed seeds "
        f"{sorted(SYMBOLS.values())}."
    )
    print(
        "SYNTHETIC seeded random walk, zero drift. Every performance number below\n"
        "is a mechanical check on the code, not evidence that anything works on\n"
        "real markets."
    )

    print(_banner("1. SCANNER"))
    universe = Universe(name="demo-crypto-equity-fx", bars_by_symbol=bars_by_symbol)
    asof = bars_by_symbol["BTC-USD"][-1].ts
    report = Scanner().scan(universe, asof)
    print(f"universe {report.universe!r} as of {asof.date()}, {len(report.results)} scored, "
          f"{len(report.skipped)} skipped\n")
    for result in report.results:
        print(f"  {result.symbol:<10} {result.score:.4f}")
    print("\nFull decomposition of the top-ranked symbol:\n")
    print(report.top(1)[0].explain())

    print(_banner("2. BACKTEST — IN-SAMPLE ONLY"))
    result = run_backtest(
        bars_by_symbol, DonchianBreakout(), initial_cash=100_000.0, execution=EXECUTION
    )
    print("Whole history, one fixed parameter set, no out-of-sample split.")
    print("IN-SAMPLE ONLY — do not quote these as evidence of edge.\n")
    print(compute_metrics(result).report())
    print(f"unfilled orders     {result.unfilled_orders}")

    print(_banner("3. BACKTEST — WALK-FORWARD (OUT-OF-SAMPLE)"))
    grid = [
        {"entry_window": e, "exit_window": x}
        for e in (10, 20, 40)
        for x in (5, 10, 20)
    ]
    wf = walk_forward(
        bars_by_symbol,
        lambda p: DonchianBreakout(int(p["entry_window"]), int(p["exit_window"])),
        grid,
        n_folds=4,
        train_bars=400,
        test_bars=100,
        initial_cash=100_000.0,
        execution=EXECUTION,
    )
    print(wf.report())

    print(_banner("4. TRADE JOURNAL"))
    print("Fed from the simulated fills of section 2. On real use, feed it your")
    print("broker's filled-order export instead.\n")
    journal = build_journal(result.fills)
    print(journal.report())

    print(_banner("5. NEWS AGGREGATOR"))
    t0 = datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc)
    headlines = [
        Headline("wire-a", "Bitcoin ETF flows hit weekly record", "https://example.invalid/a1", t0),
        Headline("wire-b", "Bitcoin ETF flows hit weekly record!", "https://example.invalid/b1", t0 + timedelta(minutes=20)),
        Headline("wire-a", "Ethereum upgrade scheduled for next quarter", "https://example.invalid/a2", t0 + timedelta(hours=2)),
        Headline("desk-notes", "Apple supplier guidance trimmed", "https://example.invalid/c1", t0 + timedelta(hours=3)),
        Headline("wire-b", "Central bank holds rates steady", "https://example.invalid/b2", t0 + timedelta(hours=4)),
    ]
    keywords = {
        "BTC-USD": ["bitcoin", "btc"],
        "ETH-USD": ["ethereum", "eth"],
        "AAPL": ["apple", "aapl"],
    }
    digest = aggregate(headlines, keywords)
    print(digest.report())

    print(_banner("6. ALERTS (ADVISORY)"))
    alerts = scan_threshold_alerts(report, min_score=0.55, digest=digest)
    dd = drawdown_alert(journal.overall, limit=1_000.0, ts=asof)
    if dd:
        alerts.append(dd)
    if not alerts:
        print("No rule crossed its threshold on this run.")
    for alert in alerts:
        print(alert.render())
        print()


if __name__ == "__main__":
    main()
