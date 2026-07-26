"""The demo run must stay reproducible: it is what performance claims cite."""

import pytest

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.metrics import compute_metrics
from quantlab.demo import EXECUTION, DonchianBreakout, build_bars, main


def test_demo_bars_are_identical_across_calls():
    assert build_bars() == build_bars()


def test_demo_in_sample_backtest_is_reproducible():
    bars = build_bars()
    a = compute_metrics(run_backtest(bars, DonchianBreakout(), initial_cash=100_000.0, execution=EXECUTION))
    b = compute_metrics(run_backtest(bars, DonchianBreakout(), initial_cash=100_000.0, execution=EXECUTION))
    assert a == b


def test_demo_runs_end_to_end_and_labels_synthetic_data(capsys):
    main()
    out = capsys.readouterr().out
    assert "SYNTHETIC" in out
    assert "IN-SAMPLE ONLY" in out
    assert "OUT-OF-SAMPLE" in out
    for section in ("1. SCANNER", "2. BACKTEST", "3. BACKTEST", "4. TRADE JOURNAL",
                    "5. NEWS AGGREGATOR", "6. ALERTS"):
        assert section in out


def test_donchian_breakout_only_buys_on_a_new_high():
    """Entry requires the close to exceed the PRIOR channel high, not equal it."""
    from datetime import datetime, timedelta, timezone

    from quantlab.backtest.engine import BarContext, Portfolio
    from quantlab.data.types import Bar

    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    flat = [Bar("X", t0 + timedelta(days=i), 100, 100, 100, 100, 10) for i in range(60)]
    ctx = BarContext(ts=flat[-1].ts, symbol="X", history=flat, portfolio=Portfolio(cash=1000.0))
    assert DonchianBreakout(20, 10).on_bar(ctx) == []

    breakout = flat[:-1] + [Bar("X", flat[-1].ts, 100, 120, 100, 120, 10)]
    ctx = BarContext(ts=flat[-1].ts, symbol="X", history=breakout, portfolio=Portfolio(cash=1000.0))
    orders = DonchianBreakout(20, 10).on_bar(ctx)
    assert len(orders) == 1 and orders[0].side == "buy"
    assert orders[0].risk_per_unit is not None and orders[0].risk_per_unit > 0
