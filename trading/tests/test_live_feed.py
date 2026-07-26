"""Feed tests. These run offline: candle parsing is tested directly.

The one behaviour that matters most here is that a candle which has not closed
yet never becomes a Bar.
"""

from datetime import datetime, timedelta, timezone

import pytest

from quantlab.live.feed import GRANULARITIES, FeedError, fetch_bars, parse_candles

H = 3600
# Venue row order: [start, low, high, open, close, volume]
T_START = int(datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).timestamp())


def row(offset_hours, low=90.0, high=110.0, open_=100.0, close=105.0, volume=7.0):
    return [T_START + offset_hours * H, low, high, open_, close, volume]


def at(hours):
    return datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc) + timedelta(hours=hours)


def test_timestamp_is_converted_from_bar_start_to_bar_close():
    bars = parse_candles([row(0)], "BTC-USD", H, now=at(10))
    assert bars[0].ts == at(1)  # start 12:00 + 1h granularity


def test_venue_column_order_is_mapped_correctly():
    bars = parse_candles([row(0, low=1.0, high=9.0, open_=2.0, close=8.0, volume=3.0)],
                         "BTC-USD", H, now=at(10))
    b = bars[0]
    assert (b.low, b.high, b.open, b.close, b.volume) == (1.0, 9.0, 2.0, 8.0, 3.0)


def test_still_forming_candle_is_dropped():
    """The newest candle is usually partial; it must never reach a strategy."""
    rows = [row(0), row(1), row(2)]
    # now is 14:30 -> the 14:00 candle closes at 15:00 and is still forming
    bars = parse_candles(rows, "BTC-USD", H, now=at(2.5))
    assert [b.ts for b in bars] == [at(1), at(2)]


def test_a_candle_closing_exactly_now_is_kept():
    bars = parse_candles([row(0)], "BTC-USD", H, now=at(1))
    assert len(bars) == 1


def test_all_candles_dropped_when_none_have_closed():
    assert parse_candles([row(0), row(1)], "BTC-USD", H, now=at(0.5)) == []


def test_bars_are_returned_oldest_first_regardless_of_venue_order():
    bars = parse_candles([row(2), row(0), row(1)], "BTC-USD", H, now=at(10))
    assert [b.ts for b in bars] == [at(1), at(2), at(3)]


def test_symbol_is_stamped_on_every_bar():
    bars = parse_candles([row(0), row(1)], "ETH-USD", H, now=at(10))
    assert {b.symbol for b in bars} == {"ETH-USD"}


def test_malformed_row_is_rejected():
    with pytest.raises(FeedError, match="malformed candle row"):
        parse_candles([[T_START, 1.0, 2.0]], "BTC-USD", H, now=at(10))


def test_unsupported_granularity_is_rejected_before_any_request():
    with pytest.raises(FeedError, match="not supported by the venue"):
        fetch_bars("BTC-USD", granularity=137)


def test_supported_granularities_are_the_documented_set():
    assert set(GRANULARITIES) == {60, 300, 900, 3600, 21600, 86400}


def test_parsed_bars_satisfy_the_bar_invariants():
    bars = parse_candles([row(i) for i in range(5)], "BTC-USD", H, now=at(10))
    for b in bars:
        assert b.high >= max(b.open, b.close)
        assert b.low <= min(b.open, b.close)
        assert b.ts.tzinfo is not None
