from datetime import datetime, timezone

import pytest

from quantlab.data.sources import load_csv_bars, synthetic_bars
from quantlab.data.types import as_of

CSV = """ts,open,high,low,close,volume
2024-01-03T00:00:00+00:00,3,4,2,3.5,300
2024-01-01T00:00:00+00:00,1,2,0.5,1.5,100
2024-01-02T00:00:00+00:00,2,3,1.5,2.5,200
"""


def test_load_csv_sorts_by_time(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text(CSV)
    bars = load_csv_bars(p, "X")
    assert [b.ts.day for b in bars] == [1, 2, 3]
    assert bars[0].close == 1.5
    assert all(b.symbol == "X" for b in bars)


def test_load_csv_rejects_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("ts,open,high,low,close\n2024-01-01T00:00:00+00:00,1,2,0.5,1.5\n")
    with pytest.raises(ValueError, match="missing required column"):
        load_csv_bars(p, "X")


def test_load_csv_reports_bad_timestamp_with_line_number(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("ts,open,high,low,close,volume\nnot-a-date,1,2,0.5,1.5,10\n")
    with pytest.raises(ValueError, match=r"bad.csv:2: bad ts"):
        load_csv_bars(p, "X")


def test_naive_timestamps_are_treated_as_utc(tmp_path):
    p = tmp_path / "naive.csv"
    p.write_text("ts,open,high,low,close,volume\n2024-01-01T00:00:00,1,2,0.5,1.5,10\n")
    assert load_csv_bars(p, "X")[0].ts.tzinfo == timezone.utc


def test_synthetic_bars_are_deterministic_for_a_seed():
    a = synthetic_bars("X", 50, seed=42)
    b = synthetic_bars("X", 50, seed=42)
    c = synthetic_bars("X", 50, seed=43)
    assert a == b
    assert a != c


def test_synthetic_bars_have_consistent_ohlc():
    for bar in synthetic_bars("X", 200, seed=5):
        assert bar.high >= max(bar.open, bar.close)
        assert bar.low <= min(bar.open, bar.close)
        assert bar.volume > 0


def test_as_of_is_inclusive_and_drops_the_future():
    bars = synthetic_bars("X", 10, seed=1)
    cut = bars[4].ts
    visible = as_of(bars, cut)
    assert len(visible) == 5
    assert visible[-1].ts == cut
    assert all(b.ts <= cut for b in visible)


def test_as_of_before_all_bars_is_empty():
    bars = synthetic_bars("X", 10, seed=1)
    assert as_of(bars, datetime(2019, 1, 1, tzinfo=timezone.utc)) == []
