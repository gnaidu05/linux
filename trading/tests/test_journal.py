from datetime import datetime, timedelta, timezone

import pytest

from quantlab.journal.matcher import match_fills
from quantlab.journal.models import ClosedTrade, Fill
from quantlab.journal.stats import breakdown, build_journal, compute_stats

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def fill(day, side, qty, price, **kw):
    return Fill(T0 + timedelta(days=day), kw.pop("symbol", "X"), side, qty, price, **kw)


def trade(pnl_per_unit, qty=1.0, **kw):
    return ClosedTrade(
        symbol=kw.get("symbol", "X"),
        direction="long",
        qty=qty,
        entry_ts=T0,
        entry_price=100.0,
        exit_ts=T0 + timedelta(days=1),
        exit_price=100.0 + pnl_per_unit,
        fees=kw.get("fees", 0.0),
        setup=kw.get("setup", "s"),
        timeframe=kw.get("timeframe", "1d"),
        risk_per_unit=kw.get("risk_per_unit"),
    )


# --- matching ----------------------------------------------------------------


def test_simple_long_round_trip():
    result = match_fills([fill(0, "buy", 10, 100.0), fill(1, "sell", 10, 110.0)])
    assert len(result.closed) == 1
    t = result.closed[0]
    assert t.direction == "long"
    assert t.qty == 10
    assert t.gross_pnl == pytest.approx(100.0)
    assert result.open_positions == []


def test_short_round_trip_profits_when_price_falls():
    result = match_fills([fill(0, "sell", 5, 100.0), fill(1, "buy", 5, 90.0)])
    t = result.closed[0]
    assert t.direction == "short"
    assert t.gross_pnl == pytest.approx(50.0)


def test_fees_from_both_legs_are_charged_to_the_trade():
    result = match_fills([
        fill(0, "buy", 10, 100.0, fee=2.0),
        fill(1, "sell", 10, 110.0, fee=3.0),
    ])
    t = result.closed[0]
    assert t.fees == pytest.approx(5.0)
    assert t.net_pnl == pytest.approx(95.0)


def test_partial_exit_leaves_the_rest_open():
    result = match_fills([fill(0, "buy", 10, 100.0), fill(1, "sell", 4, 110.0)])
    assert len(result.closed) == 1
    assert result.closed[0].qty == 4
    assert len(result.open_positions) == 1
    assert result.open_positions[0].qty == pytest.approx(6.0)
    assert result.open_positions[0].direction == "long"


def test_fifo_matches_the_oldest_lot_first():
    result = match_fills([
        fill(0, "buy", 5, 100.0),
        fill(1, "buy", 5, 200.0),
        fill(2, "sell", 5, 150.0),
    ])
    assert len(result.closed) == 1
    assert result.closed[0].entry_price == pytest.approx(100.0)  # the 100 lot, not the 200
    assert result.open_positions[0].avg_price == pytest.approx(200.0)


def test_scaling_out_across_two_lots_creates_two_trades():
    result = match_fills([
        fill(0, "buy", 5, 100.0),
        fill(1, "buy", 5, 200.0),
        fill(2, "sell", 8, 150.0),
    ])
    assert [t.qty for t in result.closed] == [5, 3]
    assert [t.entry_price for t in result.closed] == [100.0, 200.0]
    assert result.open_positions[0].qty == pytest.approx(2.0)


def test_flipping_through_zero_closes_the_long_and_opens_a_short():
    result = match_fills([fill(0, "buy", 5, 100.0), fill(1, "sell", 8, 110.0)])
    assert len(result.closed) == 1
    assert result.closed[0].direction == "long"
    assert result.open_positions[0].direction == "short"
    assert result.open_positions[0].qty == pytest.approx(3.0)


def test_fills_are_matched_in_time_order_regardless_of_input_order():
    ordered = match_fills([fill(0, "buy", 1, 100.0), fill(1, "sell", 1, 110.0)])
    shuffled = match_fills([fill(1, "sell", 1, 110.0), fill(0, "buy", 1, 100.0)])
    assert ordered.closed == shuffled.closed


def test_separate_symbols_do_not_match_against_each_other():
    result = match_fills([
        fill(0, "buy", 1, 100.0, symbol="X"),
        fill(1, "sell", 1, 110.0, symbol="Y"),
    ])
    assert result.closed == []
    assert {p.symbol for p in result.open_positions} == {"X", "Y"}


def test_entry_metadata_is_carried_onto_the_closed_trade():
    result = match_fills([
        fill(0, "buy", 1, 100.0, setup="breakout", timeframe="4h", risk_per_unit=5.0),
        fill(1, "sell", 1, 110.0, setup="ignored-on-exit", timeframe="ignored"),
    ])
    t = result.closed[0]
    assert (t.setup, t.timeframe, t.risk_per_unit) == ("breakout", "4h", 5.0)


# --- R multiples -------------------------------------------------------------


def test_r_multiple_is_net_pnl_over_initial_risk():
    result = match_fills([
        fill(0, "buy", 2, 100.0, risk_per_unit=5.0),
        fill(1, "sell", 2, 110.0),
    ])
    assert result.closed[0].r_multiple == pytest.approx(2.0)  # 20 profit / (5 * 2)


def test_r_multiple_is_none_without_a_recorded_stop():
    result = match_fills([fill(0, "buy", 1, 100.0), fill(1, "sell", 1, 110.0)])
    assert result.closed[0].r_multiple is None


def test_r_statistics_only_count_trades_that_recorded_a_stop():
    trades = [trade(10.0, risk_per_unit=5.0), trade(-5.0), trade(20.0, risk_per_unit=10.0)]
    s = compute_stats(trades)
    assert s.n_trades == 3
    assert s.n_trades_with_r == 2
    assert s.expectancy_r == pytest.approx((2.0 + 2.0) / 2)


def test_report_says_r_is_unavailable_when_no_stop_was_recorded():
    s = compute_stats([trade(10.0), trade(-5.0)])
    assert s.expectancy_r is None
    assert "0 of 2 trades recorded an initial stop" in s.report()


# --- statistics --------------------------------------------------------------


def test_win_rate_and_expectancy():
    s = compute_stats([trade(10.0), trade(10.0), trade(-5.0), trade(-15.0)])
    assert s.n_wins == 2 and s.n_losses == 2
    assert s.win_rate == pytest.approx(0.5)
    assert s.net_pnl == pytest.approx(0.0)
    assert s.expectancy == pytest.approx(0.0)
    assert s.avg_win == pytest.approx(10.0)
    assert s.avg_loss == pytest.approx(-10.0)


def test_profit_factor():
    s = compute_stats([trade(30.0), trade(-10.0)])
    assert s.profit_factor == pytest.approx(3.0)


def test_profit_factor_is_none_rather_than_infinite_when_there_are_no_losses():
    s = compute_stats([trade(10.0), trade(20.0)])
    assert s.profit_factor is None
    assert "n/a (no losses)" in s.report()


def test_closed_trade_drawdown_follows_the_trade_sequence():
    s = compute_stats([trade(100.0), trade(-60.0), trade(-10.0), trade(20.0)])
    assert s.max_drawdown == pytest.approx(70.0)


def test_empty_history_produces_zeroed_stats_not_an_error():
    s = compute_stats([])
    assert s.n_trades == 0
    assert s.expectancy == 0.0
    assert s.profit_factor is None
    assert s.expectancy_r is None


def test_breakdown_by_setup_partitions_the_trades():
    trades = [trade(10.0, setup="a"), trade(-5.0, setup="a"), trade(7.0, setup="b")]
    table = breakdown(trades, "setup")
    assert set(table) == {"a", "b"}
    assert table["a"].n_trades == 2
    assert table["b"].net_pnl == pytest.approx(7.0)
    assert sum(s.n_trades for s in table.values()) == len(trades)


# --- end-to-end journal ------------------------------------------------------


def test_open_positions_are_excluded_from_realized_statistics():
    fills = [
        fill(0, "buy", 10, 100.0, setup="a"),
        fill(1, "sell", 10, 110.0, setup="a"),
        fill(2, "buy", 5, 500.0, setup="b"),  # still open at the end
    ]
    report = build_journal(fills)
    assert report.overall.n_trades == 1
    assert report.overall.net_pnl == pytest.approx(100.0)
    assert "b" not in report.by_setup
    assert len(report.match.open_positions) == 1
    assert "still open and excluded" in report.report()


def test_journal_breakdowns_cover_setup_timeframe_and_symbol():
    fills = [
        fill(0, "buy", 1, 100.0, symbol="X", setup="a", timeframe="1d"),
        fill(1, "sell", 1, 110.0, symbol="X"),
        fill(2, "buy", 1, 50.0, symbol="Y", setup="b", timeframe="4h"),
        fill(3, "sell", 1, 40.0, symbol="Y"),
    ]
    report = build_journal(fills)
    assert set(report.by_setup) == {"a", "b"}
    assert set(report.by_timeframe) == {"1d", "4h"}
    assert set(report.by_symbol) == {"X", "Y"}
    assert report.overall.n_trades == 2


def test_journal_consumes_backtest_fills():
    """The backtester's fills are directly journalable — same Fill type."""
    from quantlab.backtest.engine import run_backtest
    from quantlab.backtest.execution import Order
    from quantlab.data.sources import synthetic_bars

    class Churn:
        def on_bar(self, ctx):
            if len(ctx.history) < 5:
                return []
            if ctx.position() == 0:
                return [Order(ctx.symbol, "buy", 1.0, setup="churn", risk_per_unit=1.0)]
            return [Order(ctx.symbol, "sell", ctx.position(), setup="churn")]

    result = run_backtest({"X": synthetic_bars("X", 60, seed=3)}, Churn())
    report = build_journal(result.fills)
    assert report.overall.n_trades > 0
    assert set(report.by_setup) == {"churn"}
