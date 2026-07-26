from datetime import datetime, timedelta, timezone

import pytest

from quantlab.backtest.execution import ExecutionModel, Order
from quantlab.data.types import Bar
from quantlab.live.paper import PaperBroker, PaperState, fill_from_dict, fill_to_dict
from quantlab.journal.models import Fill

T0 = datetime(2024, 6, 1, tzinfo=timezone.utc)
NO_COST = ExecutionModel(fee_bps=0.0, slippage_bps=0.0)


def bars(prices, symbol="X", start=0):
    return [
        Bar(symbol, T0 + timedelta(hours=start + i), p, p, p, p, 10.0)
        for i, p in enumerate(prices)
    ]


class BuyOnce:
    """Buys 1 unit the first time it is asked, then holds."""

    def __init__(self):
        self.fired = False

    def on_bar(self, ctx):
        if self.fired:
            return []
        self.fired = True
        return [Order(ctx.symbol, "buy", 1.0)]


class Never:
    def on_bar(self, ctx):
        return []


# --- bootstrap behaviour -----------------------------------------------------


def test_first_cycle_places_no_trades():
    """The paper record must not be back-filled over history it did not run."""
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    cycle = broker.advance({"X": bars([10, 11, 12, 13])}, BuyOnce())
    assert cycle.bootstrapped is True
    assert cycle.bars_processed == 0
    assert cycle.fills == []
    assert broker.state.positions == {}


def test_first_cycle_adopts_the_newest_closed_bar_as_its_start():
    history = bars([10, 11, 12, 13])
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    assert broker.state.last_ts == history[-1].ts.isoformat()
    assert broker.state.started_at is not None


def test_second_cycle_only_processes_genuinely_new_bars():
    history = bars([10, 11, 12, 13])
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())

    extended = history + bars([14, 15], start=4)
    cycle = broker.advance({"X": extended}, Never())
    assert cycle.bootstrapped is False
    assert cycle.bars_processed == 2


def test_a_cycle_with_no_new_bars_does_nothing():
    history = bars([10, 11, 12])
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    cycle = broker.advance({"X": history}, BuyOnce())
    assert cycle.bars_processed == 0
    assert cycle.fills == []


# --- execution semantics match the backtester --------------------------------


def test_orders_fill_at_the_next_bar_open_not_the_signal_bar():
    history = bars([10, 10, 10])
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())  # bootstrap at bar index 2

    signal_bar = Bar("X", T0 + timedelta(hours=3), 20, 20, 20, 20, 10)
    next_bar = Bar("X", T0 + timedelta(hours=4), 30, 35, 30, 35, 10)

    strategy = BuyOnce()
    cycle = broker.advance({"X": history + [signal_bar]}, strategy)
    assert cycle.fills == []  # order queued, nothing to fill against yet
    assert len(broker.state.pending) == 1

    cycle = broker.advance({"X": history + [signal_bar, next_bar]}, Never())
    assert len(cycle.fills) == 1
    assert cycle.fills[0].price == pytest.approx(30.0)  # next bar's OPEN
    assert cycle.fills[0].ts == next_bar.ts


def test_pending_orders_survive_a_restart():
    history = bars([10, 10, 10])
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    signal_bar = Bar("X", T0 + timedelta(hours=3), 20, 20, 20, 20, 10)
    broker.advance({"X": history + [signal_bar]}, BuyOnce())

    # Simulate a process restart: rebuild the broker from serialized state only.
    revived = PaperBroker(PaperState.from_dict(broker.state.to_dict()), NO_COST)
    next_bar = Bar("X", T0 + timedelta(hours=4), 30, 30, 30, 30, 10)
    cycle = revived.advance({"X": history + [signal_bar, next_bar]}, Never())
    assert len(cycle.fills) == 1
    assert revived.state.positions == {"X": 1.0}


def test_restart_does_not_replay_bars_already_traded():
    history = bars([10, 11, 12, 13, 14, 15])
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history[:3]}, Never())
    broker.advance({"X": history}, BuyOnce())
    seen = broker.state.last_ts

    revived = PaperBroker(PaperState.from_dict(broker.state.to_dict()), NO_COST)
    cycle = revived.advance({"X": history}, BuyOnce())
    assert cycle.bars_processed == 0
    assert revived.state.last_ts == seen


def test_costs_are_applied_to_paper_fills():
    history = bars([100.0, 100.0, 100.0])
    broker = PaperBroker(PaperState(cash=10_000.0), ExecutionModel(fee_bps=10.0, slippage_bps=10.0))
    broker.advance({"X": history}, Never())
    signal = Bar("X", T0 + timedelta(hours=3), 100, 100, 100, 100, 10)
    broker.advance({"X": history + [signal]}, BuyOnce())
    nxt = Bar("X", T0 + timedelta(hours=4), 100, 100, 100, 100, 10)
    cycle = broker.advance({"X": history + [signal, nxt]}, Never())
    fill = cycle.fills[0]
    assert fill.price == pytest.approx(100.10)  # slippage against the buyer
    assert fill.fee > 0


def test_cash_and_positions_persist_across_cycles():
    history = bars([10.0] * 3)
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    signal = Bar("X", T0 + timedelta(hours=3), 10, 10, 10, 10, 10)
    broker.advance({"X": history + [signal]}, BuyOnce())
    nxt = Bar("X", T0 + timedelta(hours=4), 10, 10, 10, 10, 10)
    broker.advance({"X": history + [signal, nxt]}, Never())
    assert broker.state.cash == pytest.approx(990.0)
    assert broker.state.positions == {"X": 1.0}


def test_a_held_symbol_keeps_its_last_mark_when_its_fetch_fails():
    """A feed outage must not put a false cliff in the paper equity curve."""
    history = bars([10.0] * 3)
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    signal = Bar("X", T0 + timedelta(hours=3), 10, 10, 10, 10, 10)
    broker.advance({"X": history + [signal]}, BuyOnce())
    nxt = Bar("X", T0 + timedelta(hours=4), 10, 10, 10, 10, 10)
    held = broker.advance({"X": history + [signal, nxt]}, Never())
    assert broker.state.positions == {"X": 1.0}
    assert held.equity == pytest.approx(1000.0)

    # Next cycle: the feed returns nothing for X at all.
    outage = broker.advance({}, Never())
    assert outage.equity == pytest.approx(1000.0)  # not 990.0 with X marked at zero
    assert broker.state.marks["X"] == pytest.approx(10.0)


def test_marks_survive_a_restart():
    history = bars([10.0] * 3)
    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    revived = PaperBroker(PaperState.from_dict(broker.state.to_dict()), NO_COST)
    assert revived.state.marks["X"] == pytest.approx(10.0)


def test_strategy_never_sees_a_bar_from_the_future():
    history = bars([float(p) for p in range(1, 21)])
    seen = []

    class Watcher:
        def on_bar(self, ctx):
            seen.append((ctx.ts, ctx.history[-1].ts))
            assert all(b.ts <= ctx.ts for b in ctx.history)
            return []

    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history[:5]}, Watcher())
    broker.advance({"X": history}, Watcher())
    assert seen
    assert all(ctx_ts == last_ts for ctx_ts, last_ts in seen)


def test_flat_positions_are_dropped_from_persisted_state():
    history = bars([10.0] * 3)

    class RoundTrip:
        def __init__(self):
            self.n = 0

        def on_bar(self, ctx):
            self.n += 1
            if self.n == 1:
                return [Order(ctx.symbol, "buy", 1.0)]
            if ctx.position() > 0:
                return [Order(ctx.symbol, "sell", ctx.position())]
            return []

    broker = PaperBroker(PaperState(cash=1000.0), NO_COST)
    broker.advance({"X": history}, Never())
    more = history + bars([10.0] * 4, start=3)
    strategy = RoundTrip()
    for i in range(4, 8):
        broker.advance({"X": more[:i]}, strategy)
    assert "X" not in broker.state.positions


# --- serialization -----------------------------------------------------------


def test_fill_round_trips_through_json():
    fill = Fill(T0, "X", "buy", 2.5, 100.0, fee=1.0, setup="s", timeframe="1h",
                risk_per_unit=3.0)
    assert fill_from_dict(fill_to_dict(fill)) == fill


def test_fill_with_no_stop_round_trips():
    fill = Fill(T0, "X", "sell", 1.0, 50.0)
    assert fill_from_dict(fill_to_dict(fill)).risk_per_unit is None


def test_paper_state_round_trips_through_json():
    state = PaperState(cash=5.0, positions={"X": 1.0}, pending=[], last_ts="t",
                       started_at="s", marks={"X": 9.0})
    assert PaperState.from_dict(state.to_dict()) == state
