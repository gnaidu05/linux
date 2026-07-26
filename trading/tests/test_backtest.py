from datetime import datetime, timedelta, timezone

import pytest

from quantlab.backtest.engine import BarContext, Portfolio, run_backtest
from quantlab.backtest.execution import ExecutionModel, Order
from quantlab.backtest.metrics import compute_metrics, equity_returns, max_drawdown
from quantlab.data.sources import synthetic_bars
from quantlab.data.types import Bar
from quantlab.journal.models import Fill

T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
NO_COST = ExecutionModel(fee_bps=0.0, slippage_bps=0.0)


def bars_from(prices, symbol="X"):
    """One bar per price, with open == close == price so fills are exact."""
    return [
        Bar(symbol, T0 + timedelta(days=i), p, p, p, p, 100.0)
        for i, p in enumerate(prices)
    ]


class BuyOnBar:
    """Buys ``qty`` on the close of bar index ``at`` and never trades again."""

    def __init__(self, at, qty=10.0, side="buy"):
        self.at = at
        self.qty = qty
        self.side = side

    def on_bar(self, ctx):
        if len(ctx.history) - 1 == self.at:
            return [Order(ctx.symbol, self.side, self.qty)]
        return []


class DoNothing:
    def on_bar(self, ctx):
        return []


# --- execution model ---------------------------------------------------------


def test_slippage_moves_the_price_against_the_trader():
    m = ExecutionModel(slippage_bps=10.0)
    assert m.fill_price("buy", 100.0) == pytest.approx(100.10)
    assert m.fill_price("sell", 100.0) == pytest.approx(99.90)


def test_fee_is_bps_of_notional():
    assert ExecutionModel(fee_bps=5.0).fee(100.0, 2.0) == pytest.approx(0.10)


# --- portfolio ---------------------------------------------------------------


def test_buy_reduces_cash_by_notional_plus_fee():
    p = Portfolio(cash=1000.0)
    p.apply(Fill(T0, "X", "buy", 2.0, 100.0, fee=1.0))
    assert p.cash == pytest.approx(799.0)
    assert p.position("X") == 2.0


def test_sell_increases_cash_and_can_go_short():
    p = Portfolio(cash=1000.0)
    p.apply(Fill(T0, "X", "sell", 2.0, 100.0, fee=1.0))
    assert p.cash == pytest.approx(1199.0)
    assert p.position("X") == -2.0


def test_equity_marks_positions_at_the_latest_close():
    p = Portfolio(cash=0.0, positions={"X": 3.0}, marks={"X": 50.0})
    assert p.equity() == pytest.approx(150.0)


# --- point-in-time correctness ----------------------------------------------


def test_order_fills_at_the_next_bar_open_not_the_signal_bar():
    bars = {"X": [
        Bar("X", T0, 10, 10, 10, 10, 100),
        Bar("X", T0 + timedelta(days=1), 20, 25, 20, 25, 100),
    ]}
    result = run_backtest(bars, BuyOnBar(at=0, qty=1.0), initial_cash=1000.0, execution=NO_COST)
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.ts == T0 + timedelta(days=1)
    assert fill.price == pytest.approx(20.0)  # next bar's OPEN, not its close of 25


def test_order_on_the_final_bar_is_counted_unfilled():
    bars = {"X": bars_from([10, 11, 12])}
    result = run_backtest(bars, BuyOnBar(at=2), initial_cash=1000.0, execution=NO_COST)
    assert result.fills == []
    assert result.unfilled_orders == 1


def test_strategy_history_never_contains_future_bars():
    """A strategy that tries to look ahead finds nothing to look at."""
    prices = [float(p) for p in range(1, 51)]
    seen = []

    class Peeker:
        def on_bar(self, ctx):
            seen.append((ctx.ts, [b.ts for b in ctx.history]))
            assert all(b.ts <= ctx.ts for b in ctx.history), "future bar visible to strategy"
            assert ctx.history[-1].ts == ctx.ts
            return []

    run_backtest({"X": bars_from(prices)}, Peeker(), execution=NO_COST)
    assert len(seen) == len(prices)
    # history grows by exactly one bar per call
    assert [len(h) for _, h in seen] == list(range(1, len(prices) + 1))


def test_mutating_the_history_a_strategy_received_cannot_affect_later_calls():
    lengths = []

    class Vandal:
        def on_bar(self, ctx):
            lengths.append(len(ctx.history))
            ctx.history.clear()
            return []

    run_backtest({"X": bars_from([1.0, 2.0, 3.0, 4.0])}, Vandal(), execution=NO_COST)
    assert lengths == [1, 2, 3, 4]


def test_equity_is_flat_when_nothing_trades():
    result = run_backtest({"X": bars_from([10, 20, 30])}, DoNothing(), initial_cash=500.0)
    assert [p.equity for p in result.equity_curve] == [500.0, 500.0, 500.0]


def test_buy_and_hold_equity_tracks_price():
    bars = {"X": bars_from([10, 10, 20])}
    result = run_backtest(bars, BuyOnBar(at=0, qty=10.0), initial_cash=1000.0, execution=NO_COST)
    # Fill 10 units at 10 on bar 1 -> cash 900, position 10.
    assert result.equity_curve[1].equity == pytest.approx(1000.0)
    assert result.equity_curve[2].equity == pytest.approx(900.0 + 10 * 20)


def test_costs_make_a_round_trip_lose_money_on_a_flat_price():
    class RoundTrip:
        def on_bar(self, ctx):
            n = len(ctx.history)
            if n == 1:
                return [Order("X", "buy", 10.0)]
            if n == 2:
                return [Order("X", "sell", 10.0)]
            return []

    bars = {"X": bars_from([100.0] * 4)}
    costed = run_backtest(bars, RoundTrip(), initial_cash=10_000.0,
                          execution=ExecutionModel(fee_bps=5.0, slippage_bps=5.0))
    free = run_backtest(bars, RoundTrip(), initial_cash=10_000.0, execution=NO_COST)
    assert free.final_equity == pytest.approx(10_000.0)
    assert costed.final_equity < 10_000.0


def test_symbols_with_missing_bars_produce_unfilled_orders():
    bars = {
        "X": bars_from([1.0, 2.0, 3.0], "X"),
        "Y": [Bar("Y", T0, 5, 5, 5, 5, 10)],  # only exists on the first timestamp
    }

    class BuyY:
        def on_bar(self, ctx):
            return [Order("Y", "buy", 1.0)] if ctx.symbol == "Y" else []

    result = run_backtest(bars, BuyY(), execution=NO_COST)
    assert result.fills == []
    assert result.unfilled_orders == 1


# --- metrics -----------------------------------------------------------------


def test_max_drawdown_of_a_known_curve():
    from quantlab.backtest.engine import EquityPoint

    curve = [EquityPoint(T0 + timedelta(days=i), e) for i, e in enumerate([100, 120, 60, 90])]
    assert max_drawdown(curve) == pytest.approx(0.5)  # 120 -> 60


def test_max_drawdown_of_a_monotone_curve_is_zero():
    from quantlab.backtest.engine import EquityPoint

    curve = [EquityPoint(T0 + timedelta(days=i), e) for i, e in enumerate([100, 110, 120])]
    assert max_drawdown(curve) == pytest.approx(0.0)


def test_equity_returns_length_is_one_less_than_the_curve():
    result = run_backtest({"X": bars_from([10, 11, 12, 13])}, DoNothing())
    assert len(equity_returns(result.equity_curve)) == 3


def test_metrics_on_a_flat_curve_are_all_zero():
    result = run_backtest({"X": bars_from([10.0] * 30)}, DoNothing(), initial_cash=1000.0)
    m = compute_metrics(result)
    assert m.total_return == pytest.approx(0.0)
    assert m.sharpe == 0.0
    assert m.annualized_vol == pytest.approx(0.0)
    assert m.max_drawdown == pytest.approx(0.0)
    assert m.n_bars == 30


def test_metrics_report_labels_drawdown_as_in_sample_observation():
    result = run_backtest({"X": synthetic_bars("X", 50, seed=1)}, DoNothing())
    assert "worst observed in sample" in compute_metrics(result).report()


def test_backtest_is_deterministic_for_a_seed():
    bars = {"X": synthetic_bars("X", 200, seed=17)}
    a = run_backtest(bars, BuyOnBar(at=30), initial_cash=10_000.0)
    b = run_backtest(bars, BuyOnBar(at=30), initial_cash=10_000.0)
    assert [p.equity for p in a.equity_curve] == [p.equity for p in b.equity_curve]
