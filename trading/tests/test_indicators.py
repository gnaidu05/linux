from datetime import datetime, timedelta, timezone

import pytest

from quantlab.data.sources import synthetic_bars
from quantlab.data.types import Bar
from quantlab.indicators import (
    atr,
    donchian_high,
    donchian_low,
    ema,
    log_returns,
    realized_vol,
    rsi,
    sma,
    true_range,
)


def make_bars(closes, highs=None, lows=None):
    ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    highs = highs or closes
    lows = lows or closes
    return [
        Bar("X", ts + timedelta(days=i), o, h, lo, c, 100.0)
        for i, (o, h, lo, c) in enumerate(zip(closes, highs, lows, closes))
    ]


def test_sma_values_and_warmup():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_shorter_than_window_is_all_none():
    assert sma([1, 2], 5) == [None, None]


def test_ema_seeds_with_sma_then_smooths():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)  # seed = sma of first 3
    assert out[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)
    assert out[4] == pytest.approx(0.5 * 5 + 0.5 * out[3])


def test_true_range_uses_previous_close():
    bars = make_bars([10, 12], highs=[10, 13], lows=[10, 11])
    assert true_range(bars) == [None, 3.0]  # max(13-11, |13-10|, |11-10|)


def test_atr_seed_is_mean_of_first_window_true_ranges():
    closes = [10, 11, 12, 13, 14, 15]
    bars = make_bars(closes, highs=[c + 1 for c in closes], lows=[c - 1 for c in closes])
    out = atr(bars, 3)
    assert out[:3] == [None, None, None]
    trs = true_range(bars)
    assert out[3] == pytest.approx(sum(trs[1:4]) / 3)


def test_rsi_all_gains_is_100():
    out = rsi([1, 2, 3, 4, 5, 6, 7, 8], 5)
    assert out[5] == 100.0


def test_rsi_stays_in_range():
    closes = [b.close for b in synthetic_bars("X", 200, seed=7)]
    for v in rsi(closes, 14):
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_log_returns_first_is_none():
    out = log_returns([100.0, 110.0])
    assert out[0] is None
    assert out[1] == pytest.approx(0.0953101798)


def test_realized_vol_of_constant_series_is_zero():
    out = realized_vol([100.0] * 40, 20, 252)
    assert out[-1] == pytest.approx(0.0)


def test_donchian_high_excludes_current_bar():
    closes = [1, 2, 3, 10]
    bars = make_bars(closes, highs=closes, lows=closes)
    # window=3 at index 3 looks at highs 1,2,3 -> 3, not the current bar's 10
    assert donchian_high(bars, 3, exclude_current=True)[3] == 3
    assert donchian_high(bars, 3, exclude_current=False)[3] == 10


def test_donchian_low_excludes_current_bar():
    closes = [10, 9, 8, 1]
    bars = make_bars(closes, highs=closes, lows=closes)
    assert donchian_low(bars, 3, exclude_current=True)[3] == 8
    assert donchian_low(bars, 3, exclude_current=False)[3] == 1


@pytest.mark.parametrize(
    "fn",
    [
        lambda bars: sma([b.close for b in bars], 10),
        lambda bars: ema([b.close for b in bars], 10),
        lambda bars: rsi([b.close for b in bars], 10),
        lambda bars: realized_vol([b.close for b in bars], 10, 252),
        lambda bars: atr(bars, 10),
        lambda bars: donchian_high(bars, 10),
        lambda bars: donchian_low(bars, 10),
    ],
)
def test_indicators_are_causal(fn):
    """Truncating the future must not change any already-computed value.

    This is the property the backtester relies on to be point-in-time correct.
    """
    bars = synthetic_bars("X", 120, seed=11)
    full = fn(bars)
    for cut in (60, 80, 100):
        partial = fn(bars[:cut])
        assert partial == full[:cut], f"value changed when future bars were removed at {cut}"
