from datetime import datetime, timedelta, timezone

import pytest

from quantlab.data.sources import synthetic_bars
from quantlab.data.types import Bar
from quantlab.scanner.criteria import (
    StructureCriterion,
    TrendCriterion,
    Universe,
    VolatilityCriterion,
    VolumeCriterion,
    default_criteria,
)
from quantlab.scanner.engine import Scanner

T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)


def ramp(n, start=100.0, step=1.0, volume=100.0):
    bars = []
    price = start
    for i in range(n):
        bars.append(
            Bar("X", T0 + timedelta(days=i), price, price + 0.5, price - 0.5, price + step, volume)
        )
        price += step
    return bars


def test_trend_score_is_exactly_the_documented_formula():
    bars = ramp(60)
    c = TrendCriterion(fast=10, slow=20, full_scale_gap=0.10)
    comp = c.evaluate(bars)
    gap = comp.inputs["relative_gap"]
    assert comp.inputs["sma_10"] > comp.inputs["sma_20"]
    assert comp.score == pytest.approx(min(1.0, max(0.0, gap / 0.10 + 0.5)))


def test_trend_score_is_half_when_averages_are_equal():
    flat = [Bar("X", T0 + timedelta(days=i), 100, 100, 100, 100, 10) for i in range(60)]
    assert TrendCriterion(fast=10, slow=20).evaluate(flat).score == pytest.approx(0.5)


def test_volume_score_zero_at_average_and_one_at_full_scale():
    base = [Bar("X", T0 + timedelta(days=i), 100, 100, 100, 100, 100.0) for i in range(21)]
    at_avg = base[:-1] + [Bar("X", base[-1].ts, 100, 100, 100, 100, 100.0)]
    assert VolumeCriterion(window=20, full_scale_ratio=3.0).evaluate(at_avg).score == pytest.approx(0.0)

    spike = base[:-1] + [Bar("X", base[-1].ts, 100, 100, 100, 100, 1000.0)]
    comp = VolumeCriterion(window=20, full_scale_ratio=3.0).evaluate(spike)
    assert comp.score == pytest.approx(1.0)
    assert comp.inputs["ratio"] > 3.0


def test_volatility_scores_one_inside_the_band():
    bars = synthetic_bars("X", 60, seed=3, vol=0.02)
    c = VolatilityCriterion(window=20, low=0.0, high=10.0)
    assert c.evaluate(bars).score == pytest.approx(1.0)


def test_volatility_falls_off_outside_the_band():
    bars = synthetic_bars("X", 60, seed=3, vol=0.02)
    comp = VolatilityCriterion(window=20, low=5.0, high=6.0).evaluate(bars)
    assert comp.score < 1.0
    assert comp.inputs["realized_vol_annualized"] < 5.0


def test_structure_scores_one_at_a_breakout():
    bars = ramp(40)  # every close is a new high
    comp = StructureCriterion(window=20, atr_window=14).evaluate(bars)
    assert comp.score == pytest.approx(1.0)
    assert comp.inputs["distance_in_atr"] > 0


def test_structure_scores_zero_far_below_the_range_high():
    bars = ramp(40)
    crash = bars[:-1] + [Bar("X", bars[-1].ts, 50, 50, 10, 10, 100)]
    assert StructureCriterion(window=20, atr_window=14).evaluate(crash).score == pytest.approx(0.0)


def test_component_contribution_is_score_times_weight():
    comp = TrendCriterion(fast=10, slow=20, weight=2.5).evaluate(ramp(60))
    assert comp.contribution == pytest.approx(comp.score * 2.5)


def test_total_score_equals_weighted_mean_of_components():
    """No hidden term: the total is reproducible from the published components."""
    bars = synthetic_bars("X", 200, seed=9)
    scanner = Scanner()
    result = scanner.scan_symbol("X", bars, bars[-1].ts)
    expected = sum(c.contribution for c in result.components) / sum(
        c.weight for c in result.components
    )
    assert result.score == pytest.approx(expected)


def test_explain_lists_every_component_and_its_inputs():
    bars = synthetic_bars("X", 200, seed=9)
    result = Scanner().scan_symbol("X", bars, bars[-1].ts)
    text = result.explain()
    for comp in result.components:
        assert comp.name in text
        assert comp.formula in text
        for key in comp.inputs:
            assert key in text


def test_scan_is_point_in_time_and_ignores_later_bars():
    bars = synthetic_bars("X", 200, seed=9)
    asof = bars[120].ts
    from_full = Scanner().scan_symbol("X", bars, asof)
    from_truncated = Scanner().scan_symbol("X", bars[:121], asof)
    assert from_full.score == from_truncated.score


def test_scan_ranks_descending_and_breaks_ties_by_symbol():
    universe = Universe(
        "u",
        {s: synthetic_bars(s, 200, seed=i) for i, s in enumerate(["A", "B", "C", "D"])},
    )
    report = Scanner().scan(universe, universe.bars_by_symbol["A"][-1].ts)
    scores = [r.score for r in report.results]
    assert scores == sorted(scores, reverse=True)


def test_symbols_with_too_little_history_are_skipped_not_scored():
    universe = Universe(
        "u",
        {
            "LONG": synthetic_bars("LONG", 200, seed=1),
            "SHORT": synthetic_bars("SHORT", 5, seed=2),
        },
    )
    report = Scanner().scan(universe, universe.bars_by_symbol["LONG"][-1].ts)
    assert [r.symbol for r in report.results] == ["LONG"]
    assert [s.symbol for s in report.skipped] == ["SHORT"]
    assert "needs" in report.skipped[0].reason


def test_min_bars_is_the_max_over_criteria():
    scanner = Scanner(default_criteria())
    assert scanner.min_bars == max(c.min_bars() for c in default_criteria())


def test_scores_are_bounded_zero_to_one():
    universe = Universe("u", {s: synthetic_bars(s, 300, seed=i) for i, s in enumerate("ABCDEFG")})
    report = Scanner().scan(universe, universe.bars_by_symbol["A"][-1].ts)
    for result in report.results:
        assert 0.0 <= result.score <= 1.0
        for comp in result.components:
            assert 0.0 <= comp.score <= 1.0
