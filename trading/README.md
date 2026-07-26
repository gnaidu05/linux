# quantlab

A local, dependency-free trading-research toolkit: a rules-based scanner, an
event-driven backtester, a realized-trade journal, a news aggregator, and an
advisory alert layer. Python 3.11 standard library only; `pytest` is needed to
run the tests.

**Read [`LIMITATIONS.md`](LIMITATIONS.md) before quoting any number this
produces.** It is not boilerplate — it names exactly what each statistic can and
cannot support.

## What this is not

- Not a price oracle. Nothing here forecasts direction, magnitude, or a
  probability of profit, and no such feature is planned. A language model
  reading a chart cannot supply one either.
- Not connected to anything. There is no broker client, no exchange client, no
  network call, and no credential handling in the package.
  `tests/test_safety.py` asserts that across every source file, so a later edit
  cannot lose the property quietly.
- Not a source of confidence numbers without a stated method. Where a score
  exists, its formula and its raw inputs are printed alongside it.

## Install and run

```bash
cd trading
pip install -e '.[dev]'     # or just: pip install pytest
python -m pytest -q         # 196 tests
python -m quantlab.demo     # reproducible end-to-end run
```

`python -m quantlab.demo` runs all five modules on a fixed-seed synthetic price
series and prints every number with its provenance. Same output every time — it
is the run any performance claim about this toolkit should cite. The prices are
a seeded random walk with zero drift: results there test the machinery and say
nothing about real markets.

## The modules

### 1. Scanner — `quantlab.scanner`

Ranks a configurable universe by four inspectable criteria: trend (fast versus
slow moving average), volume (latest bar against its trailing average),
volatility (annualized realized volatility against a target band), and structure
(distance to the prior channel high, in ATR units).

The total is the weighted mean of the components — nothing else. Every component
carries the raw inputs and the exact formula behind its sub-score, and
`ScanResult.explain()` prints the whole calculation:

```
AAPL @ 2022-06-18T00:00:00+00:00  score=0.5000
  trend        score=1.0000 weight=1.00 contribution=0.2500
      formula: clamp01((sma_20 - sma_50) / sma_50 / 0.1 + 0.5)
      close = 168.176
      sma_20 = 170.98
      sma_50 = 156.048
      relative_gap = 0.0956881
  ...
```

A score measures how well an instrument matches the rules you wrote. It is not
expected return and not a probability. Symbols with too little history are
listed in `ScanReport.skipped` with the reason, never scored on partial data.

```python
from quantlab.scanner import Scanner, Universe

report = Scanner().scan(Universe("crypto", bars_by_symbol), asof)
print(report.top(5)[0].explain())
```

Criteria are plain dataclasses. Write your own with `min_bars()` and
`evaluate()` and pass a list to `Scanner(...)`.

### 2. Backtester — `quantlab.backtest`

Event-driven and point-in-time correct. One rule governs the loop: a strategy
sees bar *t* only after it closes, and any order it places fills at bar *t+1*'s
open, with slippage and fees applied against the trader. The strategy receives a
history list the engine builds incrementally, so it cannot index into the future
even by accident — `tests/test_backtest.py` asserts this with a strategy that
tries.

`walk_forward` fits parameters on a training window and measures them on the
window immediately after, repeatedly, and reports the out-of-sample result
beside the in-sample one plus the total number of parameter evaluations:

```
OUT-OF-SAMPLE (walk-forward, stitched test windows)
total return        +1.32%
Sharpe (rf=0)       +0.16

IN-SAMPLE ONLY (best params fit and measured on the same full period)
  Not evidence of edge. Shown to expose the gap against out-of-sample.
total return        +8.85%
Sharpe (rf=0)       +0.41

parameter grid size 9
total evaluations   45
```

That gap — 8.85% in-sample against 1.32% out-of-sample, on data with no drift to
find — is what parameter search buys you when there is nothing there. It is
printed on every walk-forward report for that reason.

### 3. Journal — `quantlab.journal`

Takes filled trades and nothing else. Matches them FIFO into closed round trips,
allocating both legs' fees, then reports win rate, expectancy, R-multiples,
profit factor, closed-trade drawdown, and breakdowns by setup, timeframe, and
symbol.

Positions still open are reported separately and excluded from every statistic.
R-multiples need an initial stop distance recorded on the entry fill; trades
without one are counted and excluded rather than given an invented denominator.

```python
from quantlab.journal import build_journal
print(build_journal(fills).report())
```

`Fill` is the same type the backtester emits, so a simulated run can be
journaled directly.

### 4. News — `quantlab.news`

Tags headlines to assets by whole-word keyword match, collapses stories several
outlets ran with near-identical wording (keeping the earliest and recording
every carrier), and keeps every source and URL so you can go read the original.

It assigns no sentiment and emits no score. See `LIMITATIONS.md` for why that
omission is deliberate rather than unfinished.

### 5. Alerts — `quantlab.alerts`

Advisory only. Fires when a scan result clears a threshold or realized drawdown
reaches a limit, and attaches the full component decomposition as evidence.
News tagged to the same symbol can be attached as context; it is labelled
`context (not scored)` and never affects whether an alert fires.

Every rendered alert ends with:

> Advisory only. This is a rule firing on past data, not a recommendation, a
> forecast, or an order.

## Bringing your own data

`load_csv_bars(path, symbol)` reads `ts,open,high,low,close,volume`, where `ts`
is an ISO-8601 bar **close** time. Fetch once with your own vendor client, save
the file, and point the toolkit at it — that keeps a run reproducible from a
fixed input.

Two things the loader cannot check for you: whether your universe list is
survivorship-free, and whether the vendor restated any of the values after the
fact. Both are covered in `LIMITATIONS.md`.

## Layout

```
quantlab/
  data/          Bar type, point-in-time as_of(), CSV loader, seeded synthetic bars
  indicators.py  Causal SMA, EMA, ATR, RSI, realized vol, Donchian channels
  scanner/       Criteria with published formulas; ranking engine
  backtest/      Execution model, event-driven engine, metrics, walk-forward
  journal/       Fill and ClosedTrade, FIFO matcher, realized statistics
  news/          Headline, keyword tagging, dedupe, digest
  alerts/        Advisory rules over the above
  demo.py        Reproducible end-to-end run
tests/           196 tests, including causality, no-look-ahead, and safety checks
```
