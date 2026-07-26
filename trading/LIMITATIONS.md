# What these numbers can and cannot support

This document is the counterweight to every statistic the toolkit prints. Read
it before quoting anything from a run.

## The short version

Nothing in `quantlab` forecasts price. There is no model here that outputs a
direction, a target, or a probability of profit, and no such thing is planned.
The scanner ranks rule matches, the backtester measures what a rule set would
have done on a specific price history, the journal describes trades that already
closed, and the news module organizes reading. Each is a description of the
past. None is a prediction of the future.

A large-language model looking at a chart cannot fix this. It has no access to
the order flow, positioning, and information that move prices, and its fluency
makes a confident-sounding directional call easy to produce and impossible to
justify. Confidence expressed without a stated, testable method behind it is
decoration.

## Look-ahead bias

Look-ahead is using information at time *t* that was not knowable at time *t*.
It is the most common reason a backtest looks good and live trading does not.

What the toolkit does about it:

- `Bar.ts` is the bar's **close** time — the instant the bar became known.
- `data.as_of(bars, ts)` is the only sanctioned way to slice history, and it is
  inclusive of `ts` and excludes everything after.
- Every indicator in `indicators.py` computes element *i* from elements `0..i`
  only. `tests/test_indicators.py::test_indicators_are_causal` asserts this by
  truncating the future and checking no earlier value moved.
- The backtester hands a strategy a history list containing only closed bars,
  and fills orders at the **next** bar's open.
  `tests/test_backtest.py::test_strategy_history_never_contains_future_bars`
  asserts a strategy cannot see past "now", and
  `test_order_fills_at_the_next_bar_open_not_the_signal_bar` asserts the
  execution delay.

What it cannot do about it: if your input CSV itself contains restated or
back-filled data — revised fundamentals, adjusted closes recomputed after a
later corporate action, an index membership list as of today — the leak is in
the file and no code here can see it.

## Survivorship bias

A universe built today from instruments that exist today silently excludes
everything that was delisted, went to zero, got acquired, or was quietly removed
from an exchange listing. Backtests on such a universe are biased upward,
sometimes severely, and the size of the bias is not knowable from inside this
toolkit. `data/sources.py` says so at the point where you load files, but it
cannot detect the problem. Fixing it requires a point-in-time universe from your
data vendor.

## Overfitting and multiple testing

If you evaluate 40 parameter sets on one price history and report the best one,
part of what you have measured is how many things you tried. This is why
`walk_forward` exists, and why `WalkForwardResult.trials` is reported next to
the results: a reader needs the count to judge the in-sample number.

- **Out-of-sample** figures come from test windows chosen strictly after the
  training window used to pick parameters. Quote these.
- **In-sample** figures come from fitting and measuring on the same data. The
  report labels them `IN-SAMPLE ONLY` and states they are not evidence of edge.
  They exist so the gap between the two is visible.

Walk-forward does not eliminate overfitting. Running many walk-forwards over the
same price history and keeping the configuration whose out-of-sample number
looks best leaks information exactly the same way, only slower. The number of
distinct ideas you have tested against a given dataset is a real quantity even
when nobody writes it down.

## Fills, fees, and slippage

`ExecutionModel` charges a flat basis-point commission and a flat basis-point
price concession against the trader. That is a floor on realistic cost, not an
estimate of yours. Real slippage depends on order size versus book depth, time
of day, volatility at the moment of the order, and whether you are trading with
or against the flow.

Explicitly **not modelled**, all of which make live results worse than
simulated ones: partial fills, queue position, market impact that scales with
size, borrow availability and cost for shorts, margin calls, funding rates on
perpetuals, dividends, splits, and halts.

## The statistics themselves

- **Sharpe ratio** — computed with a zero risk-free rate from bar-to-bar simple
  returns, annualized by multiplying by the square root of the periods per year.
  That scaling assumes serially independent, roughly normal returns. Trading
  returns are neither, which flatters trend-following and penalizes
  mean-reversion. On a few hundred bars its sampling error is large enough that
  ranking strategies by it is unreliable.
- **Maximum drawdown** — the worst peak-to-trough decline *observed in this
  sample*. The true worst case is unbounded above it, and a longer sample nearly
  always finds a deeper one.
- **CAGR** — derived from first and last equity only, so it inherits whatever
  luck attached to the sample's start and end dates.
- **Expectancy** (journal) — a sample mean. At 30 trades its standard error is
  wide enough that a positive value is routinely consistent with a zero-edge
  process.
- **Breakdowns by setup, timeframe, or symbol** — these slice an already small
  sample into smaller ones. The best-looking cell in a breakdown is the one most
  likely to be noise. Every cell prints its `n` for that reason.
- **Profit factor** with zero losses is reported as `n/a`, not infinity. A ratio
  with a zero denominator is unmeasured, not perfect.
- **R-multiples** require an initial stop distance recorded at entry. Trades
  without one are excluded from R statistics and counted separately, rather than
  given an invented denominator.

## Scanner scores

A scan score is the weighted mean of its component scores, and every component
publishes the raw inputs and the exact formula that produced it —
`ScanResult.explain()` prints the whole calculation.
`tests/test_scanner.py::test_total_score_equals_weighted_mean_of_components`
asserts there is no hidden term.

The score's units are "how well this instrument matches the rules I wrote". It
is not expected return, not a probability, and not a confidence. The default
weights are equal because no evidence in this repository justifies any other
choice; changing them changes the ranking, and nothing in the toolkit will tell
you which weighting is right.

## News

The aggregator tags, deduplicates, and links. It assigns no sentiment and emits
no score. Published work on headline sentiment as a price predictor finds
effects that are small, unstable across periods, and largely gone after costs at
retail speed — and a keyword tagger is far weaker than the methods in that
research. A "bullishness" number here would be one you could not act on, so
there is not one.
`tests/test_news.py::test_digest_exposes_no_sentiment_or_score_field` keeps it
that way.

## Running continuously on live data

The 24/7 service (`quantlab.live`) changes what data the toolkit sees. It does
not change what the numbers mean, and it introduces failure modes of its own.

### Partial candles

The newest candle a venue reports is almost always still forming: its high, low,
close and volume will all change before the period ends. Feeding it to a scanner
or a strategy is live trading's version of look-ahead bias, and it is the
easiest way to make a paper record look better than it is — the strategy
effectively sees where the bar ended up before deciding.

`feed.parse_candles` drops any candle whose close time has not passed, and
`tests/test_live_feed.py::test_still_forming_candle_is_dropped` asserts it. The
venue also reports each candle by its *start* time while this package defines
`Bar.ts` as the *close* time; the feed adds one granularity on the way in. That
conversion is asserted too, because getting it wrong shifts every indicator by
one bar.

### The paper record is a forward sample, and a small one

On its first cycle the paper broker adopts the newest closed bar as its starting
point and places no trades. It never back-fills a track record over history it
was not actually running for. That is the honest construction, and it means the
record starts at zero trades and grows slowly — at hourly bars, a handful of
round trips a month.

Everything in the "statistics themselves" section above applies with more force
here, because the sample is smaller. A paper record with 12 closed trades
supports essentially no conclusion about expectancy.

### Paper fills are still simulated fills

The paper broker applies the same `ExecutionModel` as the backtester: a flat
basis-point fee and a flat basis-point concession, filling at the next bar's
open. No venue confirmed any of it. Everything in the "fills, fees, and
slippage" section still applies — no queue position, no partial fills, no
impact, no borrow. A paper record is a backtest that happens to be running
forward in time on data you cannot re-fit to; that is genuinely more informative
than a backtest, and it is still not a live track record.

### Continuous operation does not accumulate evidence faster than time passes

Running 24/7 does not make results converge sooner. Waking every five minutes on
hourly bars produces twelve cycles per bar, eleven of which do nothing but
refresh a heartbeat. The number of independent observations is set by the bar
size and the calendar, not by the polling interval.

### Data coverage

The live feed reads the public Coinbase Exchange candles endpoint, which lists
**crypto only**. Equities and FX need a vendor API with an account behind it;
none is configured, so those universes stay on whatever CSVs you supply through
`load_csv_bars`. A "24/7" schedule is also literally correct only for crypto —
equities and FX have sessions, and a service polling them around the clock would
spend most of its cycles re-reading a closed market.

## Execution safety

Simulation is the only execution path in this package. There is no broker
client, no exchange client, and no credential handling anywhere in `quantlab`,
and no code that could place, modify, or cancel an order at a venue.
`tests/test_safety.py` asserts all of that against every source file, so the
property cannot be lost quietly by a later edit.

Network access exists in exactly one file, `quantlab/live/feed.py`, and it is
read-only: GET requests to a public endpoint that requires no account, with no
authentication header and no request body. The research core — data, indicators,
scanner, backtest, journal, news, alerts — remains entirely network-free, so a
backtest or a journal run cannot depend on anything outside the machine. Both
properties are asserted in `tests/test_safety.py`.

The service heartbeat carries `"mode": "paper"` and
`"live_order_routing": false` in every status document it writes, so anything
consuming that file sees the mode alongside the numbers.

The alert layer is advisory. It renders a notice to that effect on every alert
it produces.
