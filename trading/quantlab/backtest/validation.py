"""Walk-forward validation and honest reporting of parameter search.

Why this module exists: the single most common way a backtest lies is that its
parameters were chosen by looking at the same data the result is quoted on. If
you try 40 parameter sets on one price history and report the best one, the
reported edge is partly a measurement of how many things you tried.

``walk_forward`` fits parameters on a training window and measures them on the
window immediately after, repeatedly, so every number in ``oos_metrics`` comes
from data the parameter choice never saw. ``WalkForwardResult.trials`` records
how many parameter evaluations happened in total, which is the number a reader
needs to judge how much the IN-SAMPLE figure was inflated by search.

Walk-forward does not eliminate overfitting. Reusing the same price history
across many walk-forward runs, tuning the grid until the out-of-sample number
looks good, leaks information just as surely — it is just slower.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from ..data.types import Bar
from .engine import BacktestResult, EquityPoint, Strategy, run_backtest
from .execution import ExecutionModel
from .metrics import Metrics, compute_metrics, equity_returns

Params = dict[str, float | int]
StrategyFactory = Callable[[Params], Strategy]


@dataclass(frozen=True)
class Fold:
    """One train/test split, expressed as timestamp boundaries."""

    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def _timeline(bars_by_symbol: dict[str, list[Bar]]) -> list[datetime]:
    return sorted({bar.ts for bars in bars_by_symbol.values() for bar in bars})


def make_folds(
    bars_by_symbol: dict[str, list[Bar]], *, n_folds: int, train_bars: int, test_bars: int
) -> list[Fold]:
    """Build ``n_folds`` consecutive rolling train/test windows.

    Windows roll forward by ``test_bars`` each fold, so test windows are
    disjoint and each one begins where the previous ended.
    """
    timeline = _timeline(bars_by_symbol)
    needed = train_bars + n_folds * test_bars
    if len(timeline) < needed:
        raise ValueError(
            f"need {needed} timestamps for {n_folds} folds of "
            f"train={train_bars}/test={test_bars}, have {len(timeline)}"
        )
    folds = []
    for i in range(n_folds):
        tr_start = i * test_bars
        tr_end = tr_start + train_bars - 1
        te_start = tr_end + 1
        te_end = te_start + test_bars - 1
        folds.append(
            Fold(
                index=i,
                train_start=timeline[tr_start],
                train_end=timeline[tr_end],
                test_start=timeline[te_start],
                test_end=timeline[te_end],
            )
        )
    return folds


def slice_bars(
    bars_by_symbol: dict[str, list[Bar]], start: datetime, end: datetime
) -> dict[str, list[Bar]]:
    """Bars with ``start <= ts <= end``, per symbol."""
    return {
        sym: [b for b in bars if start <= b.ts <= end]
        for sym, bars in bars_by_symbol.items()
    }


@dataclass(frozen=True)
class FoldOutcome:
    """What one fold produced."""

    fold: Fold
    chosen_params: Params
    train_objective: float
    test_metrics: Metrics
    test_curve: list[EquityPoint]
    """Equity path inside the test window only."""


@dataclass(frozen=True)
class WalkForwardResult:
    """Out-of-sample result, plus the in-sample figure it should be read against."""

    folds: list[FoldOutcome]
    oos_metrics: Metrics
    """Computed on the stitched out-of-sample equity curve. This is the number
    to quote. It is still a single sample of one price history."""
    in_sample_metrics: Metrics
    """Best parameter set over the WHOLE period, measured on that same whole
    period. Reported only as a contrast: it is in-sample and is expected to look
    better than reality."""
    in_sample_params: Params
    trials: int
    """Total parameter evaluations across all folds plus the in-sample fit."""
    grid_size: int

    def report(self) -> str:
        lines = [
            "OUT-OF-SAMPLE (walk-forward, stitched test windows)",
            self.oos_metrics.report(),
            "",
            "IN-SAMPLE ONLY (best params fit and measured on the same full period)",
            "  Not evidence of edge. Shown to expose the gap against out-of-sample.",
            self.in_sample_metrics.report(),
            "",
            f"parameter grid size {self.grid_size}",
            f"total evaluations   {self.trials}",
            f"folds               {len(self.folds)}",
            "",
            "per-fold chosen parameters and out-of-sample return:",
        ]
        for outcome in self.folds:
            lines.append(
                f"  fold {outcome.fold.index}: {outcome.chosen_params} "
                f"-> OOS total return {outcome.test_metrics.total_return:+.2%}"
            )
        return "\n".join(lines)


def _slice_curve(
    curve: list[EquityPoint], start: datetime, end: datetime
) -> list[EquityPoint]:
    return [p for p in curve if start <= p.ts <= end]


def _run(
    bars: dict[str, list[Bar]],
    factory: StrategyFactory,
    params: Params,
    initial_cash: float,
    execution: ExecutionModel,
) -> BacktestResult:
    return run_backtest(
        bars, factory(params), initial_cash=initial_cash, execution=execution
    )


def walk_forward(
    bars_by_symbol: dict[str, list[Bar]],
    factory: StrategyFactory,
    grid: list[Params],
    *,
    n_folds: int,
    train_bars: int,
    test_bars: int,
    objective: Callable[[Metrics], float] = lambda m: m.sharpe,
    initial_cash: float = 100_000.0,
    execution: ExecutionModel | None = None,
    periods_per_year: int = 252,
) -> WalkForwardResult:
    """Fit on each training window, measure on the window that follows.

    Each fold's test run is fed the training bars as warmup so indicators are
    already spun up when the test window begins, but only the equity path inside
    the test window is scored. Positions opened during warmup are carried into
    the test window, which is what happens in live trading.
    """
    execution = execution or ExecutionModel()
    folds = make_folds(
        bars_by_symbol, n_folds=n_folds, train_bars=train_bars, test_bars=test_bars
    )

    outcomes: list[FoldOutcome] = []
    trials = 0
    for fold in folds:
        train = slice_bars(bars_by_symbol, fold.train_start, fold.train_end)
        best_params = grid[0]
        best_obj = float("-inf")
        for params in grid:
            trials += 1
            m = compute_metrics(
                _run(train, factory, params, initial_cash, execution),
                periods_per_year=periods_per_year,
            )
            value = objective(m)
            if value > best_obj:
                best_obj = value
                best_params = params

        warm_and_test = slice_bars(bars_by_symbol, fold.train_start, fold.test_end)
        test_result = _run(warm_and_test, factory, best_params, initial_cash, execution)
        test_curve = _slice_curve(
            test_result.equity_curve, fold.test_start, fold.test_end
        )
        test_only = BacktestResult(
            equity_curve=test_curve,
            fills=[f for f in test_result.fills if fold.test_start <= f.ts <= fold.test_end],
            unfilled_orders=test_result.unfilled_orders,
            start=fold.test_start,
            end=fold.test_end,
            initial_cash=test_curve[0].equity,
        )
        outcomes.append(
            FoldOutcome(
                fold=fold,
                chosen_params=best_params,
                train_objective=best_obj,
                test_metrics=compute_metrics(test_only, periods_per_year=periods_per_year),
                test_curve=test_curve,
            )
        )

    # Stitch the out-of-sample windows by compounding their returns end to end.
    stitched = [EquityPoint(ts=folds[0].test_start, equity=initial_cash)]
    equity = initial_cash
    for outcome in outcomes:
        returns = equity_returns(outcome.test_curve)
        for point, r in zip(outcome.test_curve[1:], returns):
            equity *= 1.0 + r
            stitched.append(EquityPoint(ts=point.ts, equity=equity))
    oos_fills = sum(o.test_metrics.n_fills for o in outcomes)
    oos_result = BacktestResult(
        equity_curve=stitched,
        fills=[],
        unfilled_orders=0,
        start=folds[0].test_start,
        end=folds[-1].test_end,
        initial_cash=initial_cash,
    )
    oos_metrics = compute_metrics(oos_result, periods_per_year=periods_per_year)
    oos_metrics = Metrics(**{**oos_metrics.__dict__, "n_fills": oos_fills})

    # In-sample contrast: best params over the entire history, scored there too.
    full_start, full_end = _timeline(bars_by_symbol)[0], _timeline(bars_by_symbol)[-1]
    full = slice_bars(bars_by_symbol, full_start, full_end)
    is_best_params = grid[0]
    is_best_metrics = None
    is_best_obj = float("-inf")
    for params in grid:
        trials += 1
        m = compute_metrics(
            _run(full, factory, params, initial_cash, execution),
            periods_per_year=periods_per_year,
        )
        if objective(m) > is_best_obj:
            is_best_obj = objective(m)
            is_best_params = params
            is_best_metrics = m

    return WalkForwardResult(
        folds=outcomes,
        oos_metrics=oos_metrics,
        in_sample_metrics=is_best_metrics,
        in_sample_params=is_best_params,
        trials=trials,
        grid_size=len(grid),
    )
