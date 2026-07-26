"""Causal technical indicators.

Every function here returns a list the same length as its input, where element
``i`` is computed from inputs ``0..i`` only, and is ``None`` while the window is
still warming up. That causality is the property the backtester depends on, and
it is asserted directly in ``tests/test_indicators.py``.

None of these functions forecast anything. They are descriptive summaries of
past prices.
"""

from __future__ import annotations

import math

from .data.types import Bar


def sma(values: list[float], window: int) -> list[float | None]:
    """Simple moving average over ``window`` samples."""
    out: list[float | None] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def ema(values: list[float], window: int) -> list[float | None]:
    """Exponential moving average, seeded with the first ``window``-sample SMA."""
    out: list[float | None] = [None] * len(values)
    if len(values) < window:
        return out
    alpha = 2.0 / (window + 1)
    prev = sum(values[:window]) / window
    out[window - 1] = prev
    for i in range(window, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def true_range(bars: list[Bar]) -> list[float | None]:
    """True range per bar. ``None`` for the first bar (no previous close)."""
    out: list[float | None] = [None] * len(bars)
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        b = bars[i]
        out[i] = max(b.high - b.low, abs(b.high - prev_close), abs(b.low - prev_close))
    return out


def atr(bars: list[Bar], window: int) -> list[float | None]:
    """Wilder's average true range."""
    tr = true_range(bars)
    out: list[float | None] = [None] * len(bars)
    first = window  # index of the last bar in the first full TR window
    if len(bars) <= first:
        return out
    seed = sum(tr[1 : window + 1]) / window  # type: ignore[arg-type]
    out[first] = seed
    prev = seed
    for i in range(first + 1, len(bars)):
        prev = (prev * (window - 1) + tr[i]) / window  # type: ignore[operator]
        out[i] = prev
    return out


def rsi(closes: list[float], window: int) -> list[float | None]:
    """Wilder's RSI on close-to-close changes, in the range 0..100."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= window:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, window + 1):
        delta = closes[i] - closes[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / window
    avg_loss = losses / window
    out[window] = _rsi_from(avg_gain, avg_loss)
    for i in range(window + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (window - 1) + max(delta, 0.0)) / window
        avg_loss = (avg_loss * (window - 1) + max(-delta, 0.0)) / window
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def log_returns(values: list[float]) -> list[float | None]:
    """Close-to-close log returns; ``None`` at index 0."""
    out: list[float | None] = [None] * len(values)
    for i in range(1, len(values)):
        out[i] = math.log(values[i] / values[i - 1])
    return out


def realized_vol(
    closes: list[float], window: int, periods_per_year: int
) -> list[float | None]:
    """Annualized realized volatility: sample stdev of log returns, scaled.

    The annualization assumes returns are independent across bars, which they
    are not exactly. Treat the output as a comparable volatility ranking, not a
    calibrated forecast of future dispersion.
    """
    rets = log_returns(closes)
    out: list[float | None] = [None] * len(closes)
    scale = math.sqrt(periods_per_year)
    for i in range(len(closes)):
        if i < window:
            continue
        w = [r for r in rets[i - window + 1 : i + 1] if r is not None]
        if len(w) < 2:
            continue
        mean = sum(w) / len(w)
        var = sum((r - mean) ** 2 for r in w) / (len(w) - 1)
        out[i] = math.sqrt(var) * scale
    return out


def donchian_high(bars: list[Bar], window: int, exclude_current: bool = True) -> list[float | None]:
    """Highest high over the trailing ``window`` bars.

    With ``exclude_current=True`` (the default) the current bar is left out, so
    comparing ``bars[i].close`` against ``donchian_high[i]`` is a genuine
    breakout test rather than a tautology.
    """
    out: list[float | None] = [None] * len(bars)
    offset = 1 if exclude_current else 0
    for i in range(len(bars)):
        start = i - window - offset + 1
        end = i - offset + 1
        if start < 0 or end <= start:
            continue
        out[i] = max(b.high for b in bars[start:end])
    return out


def donchian_low(bars: list[Bar], window: int, exclude_current: bool = True) -> list[float | None]:
    """Lowest low over the trailing ``window`` bars. See ``donchian_high``."""
    out: list[float | None] = [None] * len(bars)
    offset = 1 if exclude_current else 0
    for i in range(len(bars)):
        start = i - window - offset + 1
        end = i - offset + 1
        if start < 0 or end <= start:
            continue
        out[i] = min(b.low for b in bars[start:end])
    return out
