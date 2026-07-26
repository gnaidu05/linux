"""Bar data sources.

Two sources ship with the toolkit:

* ``load_csv_bars`` reads a local CSV you control. This is the intended path for
  real research: fetch once with your own vendor client, save it, and point the
  toolkit at the file, so a run is reproducible from a fixed input.
* ``synthetic_bars`` generates a deterministic random-walk series for tests and
  demos.

Survivorship warning: a universe assembled today from instruments that still
exist today excludes everything that was delisted, went to zero, or was
acquired. Backtest results on such a universe are biased upward and the size of
that bias is not knowable from inside this toolkit. ``load_csv_bars`` cannot
detect the problem; it is a property of how you built the file list.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .types import Bar

REQUIRED_COLUMNS = ("ts", "open", "high", "low", "close", "volume")


def load_csv_bars(path: str | Path, symbol: str) -> list[Bar]:
    """Load bars from a CSV with columns ts,open,high,low,close,volume.

    ``ts`` must be an ISO-8601 bar CLOSE time. Rows are returned sorted by time.
    This is a system boundary, so the header and the time ordering are checked.
    """
    path = Path(path)
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing required column(s): {', '.join(missing)}")
        bars = [
            Bar(
                symbol=symbol,
                ts=_parse_ts(row["ts"], path, i),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for i, row in enumerate(reader, start=2)
        ]
    bars.sort(key=lambda b: b.ts)
    return bars


def _parse_ts(raw: str, path: Path, line: int) -> datetime:
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{path}:{line}: bad ts {raw!r}: {exc}") from exc
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def synthetic_bars(
    symbol: str,
    n: int,
    *,
    seed: int,
    start: datetime | None = None,
    step: timedelta = timedelta(days=1),
    start_price: float = 100.0,
    drift: float = 0.0,
    vol: float = 0.02,
) -> list[Bar]:
    """Generate a deterministic random-walk OHLCV series.

    Same ``seed`` always gives the same bars, which is what makes the demo run
    reproducible. These are simulated prices with a known generating process:
    any performance measured on them says something about the mechanics of a
    strategy, and nothing at all about whether it would have made money.
    """
    rng = random.Random(seed)
    ts = start or datetime(2020, 1, 1, tzinfo=timezone.utc)
    price = start_price
    bars: list[Bar] = []
    for _ in range(n):
        ret = drift + rng.gauss(0.0, vol)
        open_ = price
        close = open_ * math.exp(ret)
        wick = abs(rng.gauss(0.0, vol)) * open_ * 0.5
        high = max(open_, close) + wick
        low = min(open_, close) - wick
        bars.append(
            Bar(
                symbol=symbol,
                ts=ts,
                open=open_,
                high=high,
                low=max(low, 0.01),
                close=close,
                volume=round(rng.uniform(1_000, 10_000), 2),
            )
        )
        price = close
        ts = ts + step
    return bars
