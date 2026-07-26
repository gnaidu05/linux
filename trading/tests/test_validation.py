import pytest

from quantlab.backtest.execution import ExecutionModel, Order
from quantlab.backtest.validation import make_folds, slice_bars, walk_forward
from quantlab.data.sources import synthetic_bars
from quantlab.indicators import sma

NO_COST = ExecutionModel(fee_bps=0.0, slippage_bps=0.0)


class SmaCross:
    """Long while price is above its own moving average, flat otherwise."""

    def __init__(self, window: int):
        self.window = window

    def on_bar(self, ctx):
        bars = ctx.history
        if len(bars) < self.window + 1:
            return []
        avg = sma([b.close for b in bars], self.window)[-1]
        position = ctx.position()
        if position == 0 and bars[-1].close > avg:
            qty = (ctx.portfolio.equity() * 0.5) / bars[-1].close
            return [Order(ctx.symbol, "buy", qty, setup=f"sma_{self.window}")]
        if position > 0 and bars[-1].close < avg:
            return [Order(ctx.symbol, "sell", position, setup=f"sma_{self.window}")]
        return []


def factory(params):
    return SmaCross(int(params["window"]))


GRID = [{"window": w} for w in (5, 10, 20)]


@pytest.fixture
def bars():
    return {"X": synthetic_bars("X", 600, seed=101), "Y": synthetic_bars("Y", 600, seed=202)}


# --- fold construction -------------------------------------------------------


def test_folds_roll_forward_and_test_windows_are_disjoint(bars):
    folds = make_folds(bars, n_folds=3, train_bars=200, test_bars=50)
    assert len(folds) == 3
    for f in folds:
        assert f.train_end < f.test_start
    for a, b in zip(folds, folds[1:]):
        assert a.test_end < b.test_start


def test_each_test_window_starts_immediately_after_its_training_window(bars):
    timeline = sorted({bar.ts for bs in bars.values() for bar in bs})
    for f in make_folds(bars, n_folds=3, train_bars=200, test_bars=50):
        assert timeline[timeline.index(f.train_end) + 1] == f.test_start


def test_make_folds_refuses_when_history_is_too_short(bars):
    with pytest.raises(ValueError, match="need 1100 timestamps"):
        make_folds(bars, n_folds=2, train_bars=500, test_bars=300)


def test_slice_bars_is_inclusive_on_both_ends(bars):
    all_x = bars["X"]
    sliced = slice_bars(bars, all_x[10].ts, all_x[20].ts)
    assert len(sliced["X"]) == 11
    assert sliced["X"][0].ts == all_x[10].ts
    assert sliced["X"][-1].ts == all_x[20].ts


# --- walk-forward ------------------------------------------------------------


def test_walk_forward_evaluates_every_grid_point_per_fold_plus_the_in_sample_fit(bars):
    wf = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                      execution=NO_COST)
    assert wf.grid_size == len(GRID)
    assert wf.trials == len(GRID) * (3 + 1)


def test_walk_forward_chosen_params_come_from_the_grid(bars):
    wf = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                      execution=NO_COST)
    for outcome in wf.folds:
        assert outcome.chosen_params in GRID


def test_walk_forward_scores_only_the_test_window(bars):
    wf = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                      execution=NO_COST)
    for outcome in wf.folds:
        assert outcome.test_curve[0].ts == outcome.fold.test_start
        assert outcome.test_curve[-1].ts == outcome.fold.test_end
        assert all(
            outcome.fold.test_start <= p.ts <= outcome.fold.test_end
            for p in outcome.test_curve
        )


def test_walk_forward_objective_selects_the_best_training_score(bars):
    """The chosen parameter set must be the grid's argmax on the TRAINING window."""
    from quantlab.backtest.metrics import compute_metrics
    from quantlab.backtest.engine import run_backtest

    wf = walk_forward(bars, factory, GRID, n_folds=2, train_bars=200, test_bars=50,
                      execution=NO_COST)
    for outcome in wf.folds:
        train = slice_bars(bars, outcome.fold.train_start, outcome.fold.train_end)
        scores = {
            tuple(p.items()): compute_metrics(
                run_backtest(train, factory(p), execution=NO_COST)
            ).sharpe
            for p in GRID
        }
        assert scores[tuple(outcome.chosen_params.items())] == max(scores.values())
        assert outcome.train_objective == pytest.approx(max(scores.values()))


def test_stitched_oos_curve_compounds_every_fold(bars):
    wf = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                      execution=NO_COST)
    expected = 1.0
    for outcome in wf.folds:
        curve = outcome.test_curve
        expected *= curve[-1].equity / curve[0].equity
    assert 1.0 + wf.oos_metrics.total_return == pytest.approx(expected)


def test_oos_fill_count_is_the_sum_over_folds(bars):
    wf = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                      execution=NO_COST)
    assert wf.oos_metrics.n_fills == sum(o.test_metrics.n_fills for o in wf.folds)


def test_report_labels_in_sample_and_out_of_sample_sections(bars):
    wf = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                      execution=NO_COST)
    text = wf.report()
    assert "OUT-OF-SAMPLE" in text
    assert "IN-SAMPLE ONLY" in text
    assert "Not evidence of edge" in text
    assert f"total evaluations   {wf.trials}" in text


def test_walk_forward_is_deterministic(bars):
    a = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                     execution=NO_COST)
    b = walk_forward(bars, factory, GRID, n_folds=3, train_bars=200, test_bars=50,
                     execution=NO_COST)
    assert a.oos_metrics == b.oos_metrics
    assert [o.chosen_params for o in a.folds] == [o.chosen_params for o in b.folds]


def test_in_sample_fit_is_the_grid_argmax_over_the_whole_history(bars):
    from quantlab.backtest.engine import run_backtest
    from quantlab.backtest.metrics import compute_metrics

    wf = walk_forward(bars, factory, GRID, n_folds=2, train_bars=200, test_bars=50,
                      execution=NO_COST)
    scores = {
        tuple(p.items()): compute_metrics(run_backtest(bars, factory(p), execution=NO_COST)).sharpe
        for p in GRID
    }
    assert scores[tuple(wf.in_sample_params.items())] == max(scores.values())
    assert wf.in_sample_metrics.sharpe == pytest.approx(max(scores.values()))
