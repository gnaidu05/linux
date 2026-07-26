"""Live market data over the public Coinbase Exchange candles endpoint.

This is the ONLY module in the package that opens a network connection, and it
is read-only: it issues GET requests to a public endpoint that requires no
account, sends no authentication header, and has no code path that could place
an order. ``tests/test_live_feed.py`` asserts all of that against the source.

Two correctness details that matter more than they look:

1. **Bar close times.** The venue reports each candle by its START time. The
   rest of this package defines ``Bar.ts`` as the CLOSE time, so the feed adds
   one granularity to every timestamp on the way in. Getting this wrong would
   shift every indicator by one bar.

2. **Partial candles.** The newest candle the venue returns is usually still
   forming — its high, low, close and volume will all change before the period
   ends. Feeding that to a scanner or a strategy is live-trading's version of
   look-ahead bias, and it is the single easiest way to make a paper track
   record look better than it is. ``fetch_bars`` drops any candle whose close
   time has not passed yet, and ``tests/test_live_feed.py`` asserts it.

Coverage: this venue lists crypto only. Equities and FX need a vendor API with
an account behind it; none is configured here, so those universes stay on
whatever CSVs you supply through ``load_csv_bars``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..data.types import Bar

BASE_URL = "https://api.exchange.coinbase.com"
USER_AGENT = "quantlab/0.1 (research; read-only)"

GRANULARITIES = {60: "1m", 300: "5m", 900: "15m", 3600: "1h", 21600: "6h", 86400: "1d"}


class FeedError(RuntimeError):
    """The venue could not be reached, or returned something unusable."""


def _get(url: str, timeout: float) -> list:
    """Issue one read-only GET and decode the JSON body."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise FeedError(f"{url}: HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FeedError(f"{url}: {exc}") from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FeedError(f"{url}: response was not JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise FeedError(f"{url}: expected a list of candles, got {payload!r}")
    return payload


def parse_candles(
    rows: list, symbol: str, granularity: int, now: datetime
) -> list[Bar]:
    """Convert venue candles to closed ``Bar`` objects, oldest first.

    Venue rows are ``[start, low, high, open, close, volume]``. Candles whose
    close time is at or after ``now`` are still forming and are dropped.
    """
    bars = []
    for row in rows:
        if len(row) < 6:
            raise FeedError(f"{symbol}: malformed candle row {row!r}")
        start, low, high, open_, close, volume = row[:6]
        close_ts = datetime.fromtimestamp(start + granularity, tz=timezone.utc)
        if close_ts > now:
            continue  # still forming; its values will change before it closes
        bars.append(
            Bar(
                symbol=symbol,
                ts=close_ts,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            )
        )
    bars.sort(key=lambda b: b.ts)
    return bars


def fetch_bars(
    symbol: str,
    *,
    granularity: int = 3600,
    timeout: float = 20.0,
    now: datetime | None = None,
) -> list[Bar]:
    """Fetch closed candles for one product, oldest first.

    Only bars that have actually closed are returned. The venue caps a single
    response at a few hundred candles, which is the history this returns.
    """
    if granularity not in GRANULARITIES:
        raise FeedError(
            f"granularity {granularity} not supported by the venue; "
            f"choose one of {sorted(GRANULARITIES)}"
        )
    url = f"{BASE_URL}/products/{symbol}/candles?granularity={granularity}"
    rows = _get(url, timeout)
    return parse_candles(rows, symbol, granularity, now or datetime.now(timezone.utc))


def fetch_universe(
    symbols: list[str],
    *,
    granularity: int = 3600,
    timeout: float = 20.0,
    pause: float = 0.25,
    now: datetime | None = None,
) -> tuple[dict[str, list[Bar]], dict[str, str]]:
    """Fetch several products, pausing between requests to respect rate limits.

    Returns the bars that were fetched and a map of symbol to error message for
    the ones that failed. A partial universe is reported rather than raised: one
    unreachable product should not stop a 24/7 service from screening the rest.
    """
    bars: dict[str, list[Bar]] = {}
    errors: dict[str, str] = {}
    for i, symbol in enumerate(symbols):
        if i:
            time.sleep(pause)
        try:
            bars[symbol] = fetch_bars(
                symbol, granularity=granularity, timeout=timeout, now=now
            )
        except FeedError as exc:
            errors[symbol] = str(exc)
    return bars, errors
