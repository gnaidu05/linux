"""Screening criteria.

A criterion maps a slice of history to a ``Component``: a 0..1 sub-score plus
the raw numbers that produced it. Nothing is hidden — a caller can always
recompute a component's score by hand from ``Component.inputs`` and the formula
in the criterion's docstring.

A high score means "this instrument currently matches the rules the criterion
encodes". It is not an estimate of future return and carries no probability of
profit. The rules are hand-written descriptions of past price behaviour, not a
fitted model of anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..data.types import Bar
from ..indicators import atr, donchian_high, realized_vol, sma


@dataclass(frozen=True)
class Component:
    """One criterion's contribution to a scan score."""

    name: str
    score: float
    weight: float
    inputs: dict[str, float]
    formula: str

    @property
    def contribution(self) -> float:
        """Weighted score, in the same units the total is summed in."""
        return self.score * self.weight


class Criterion(Protocol):
    """Anything that scores one instrument's history."""

    name: str
    weight: float

    def min_bars(self) -> int:
        """Bars of history required before this criterion can score."""

    def evaluate(self, bars: list[Bar]) -> Component:
        """Score ``bars``, using the final bar as 'now'."""


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class TrendCriterion:
    """Scores trend as the gap between a fast and a slow simple moving average.

    Score is ``clamp01(((fast - slow) / slow) / full_scale_gap + 0.5)``, so an
    exactly flat pair of averages scores 0.5, and the score saturates at 0 or 1
    once the averages are ``full_scale_gap`` apart in relative terms.
    """

    fast: int = 20
    slow: int = 50
    full_scale_gap: float = 0.10
    weight: float = 1.0
    name: str = "trend"

    def min_bars(self) -> int:
        return self.slow

    def evaluate(self, bars: list[Bar]) -> Component:
        closes = [b.close for b in bars]
        fast_v = sma(closes, self.fast)[-1]
        slow_v = sma(closes, self.slow)[-1]
        gap = (fast_v - slow_v) / slow_v
        return Component(
            name=self.name,
            score=_clamp01(gap / self.full_scale_gap + 0.5),
            weight=self.weight,
            inputs={
                "close": closes[-1],
                f"sma_{self.fast}": fast_v,
                f"sma_{self.slow}": slow_v,
                "relative_gap": gap,
            },
            formula=(
                f"clamp01((sma_{self.fast} - sma_{self.slow}) / sma_{self.slow} "
                f"/ {self.full_scale_gap} + 0.5)"
            ),
        )


@dataclass
class VolumeCriterion:
    """Scores current volume against its own trailing average.

    Score is ``clamp01((ratio - 1) / (full_scale_ratio - 1))`` where ``ratio``
    is the latest bar's volume over the ``window``-bar average volume. Volume at
    or below average scores 0; ``full_scale_ratio`` times average scores 1.
    """

    window: int = 20
    full_scale_ratio: float = 3.0
    weight: float = 1.0
    name: str = "volume"

    def min_bars(self) -> int:
        return self.window

    def evaluate(self, bars: list[Bar]) -> Component:
        volumes = [b.volume for b in bars]
        avg = sma(volumes, self.window)[-1]
        ratio = volumes[-1] / avg if avg else 0.0
        return Component(
            name=self.name,
            score=_clamp01((ratio - 1.0) / (self.full_scale_ratio - 1.0)),
            weight=self.weight,
            inputs={
                "volume": volumes[-1],
                f"avg_volume_{self.window}": avg,
                "ratio": ratio,
            },
            formula=f"clamp01((ratio - 1) / ({self.full_scale_ratio} - 1))",
        )


@dataclass
class VolatilityCriterion:
    """Scores how close annualized realized volatility sits to a target band.

    Volatility inside ``[low, high]`` scores 1. Outside the band the score falls
    off linearly over a width equal to the band's own width, reaching 0 one full
    band-width away. The intent is to screen out instruments too quiet to move
    and too wild to size, not to claim either regime predicts direction.
    """

    window: int = 20
    periods_per_year: int = 252
    low: float = 0.15
    high: float = 0.60
    weight: float = 1.0
    name: str = "volatility"

    def min_bars(self) -> int:
        return self.window + 1

    def evaluate(self, bars: list[Bar]) -> Component:
        closes = [b.close for b in bars]
        vol = realized_vol(closes, self.window, self.periods_per_year)[-1]
        width = self.high - self.low
        if vol < self.low:
            score = _clamp01(1.0 - (self.low - vol) / width)
        elif vol > self.high:
            score = _clamp01(1.0 - (vol - self.high) / width)
        else:
            score = 1.0
        return Component(
            name=self.name,
            score=score,
            weight=self.weight,
            inputs={
                "realized_vol_annualized": vol,
                "band_low": self.low,
                "band_high": self.high,
            },
            formula=(
                f"1 inside [{self.low}, {self.high}], else falling linearly to 0 "
                f"over {width:.4g} of annualized vol"
            ),
        )


@dataclass
class StructureCriterion:
    """Scores where price sits relative to its recent range, in ATR units.

    Score is ``clamp01(1 + (close - prior_high) / (atr_multiple * atr))``: price
    at or above the prior ``window``-bar high scores 1, and the score decays to
    0 as price sits ``atr_multiple`` ATRs below that high. The prior high
    excludes the current bar, so this measures a breakout rather than restating
    that today's high is today's high.
    """

    window: int = 20
    atr_window: int = 14
    atr_multiple: float = 2.0
    weight: float = 1.0
    name: str = "structure"

    def min_bars(self) -> int:
        return max(self.window + 1, self.atr_window + 1)

    def evaluate(self, bars: list[Bar]) -> Component:
        close = bars[-1].close
        prior_high = donchian_high(bars, self.window, exclude_current=True)[-1]
        atr_v = atr(bars, self.atr_window)[-1]
        distance = close - prior_high
        score = _clamp01(1.0 + distance / (self.atr_multiple * atr_v)) if atr_v else 0.0
        return Component(
            name=self.name,
            score=score,
            weight=self.weight,
            inputs={
                "close": close,
                f"prior_{self.window}_bar_high": prior_high,
                f"atr_{self.atr_window}": atr_v,
                "distance_in_atr": distance / atr_v if atr_v else 0.0,
            },
            formula=f"clamp01(1 + (close - prior_high) / ({self.atr_multiple} * atr))",
        )


def default_criteria() -> list[Criterion]:
    """The four criteria the scanner uses when none are supplied.

    Equal weights. There is no evidence in this repository that these weights
    are better than any others; they are a starting point to edit, and changing
    them changes the ranking.
    """
    return [
        TrendCriterion(),
        VolumeCriterion(),
        VolatilityCriterion(),
        StructureCriterion(),
    ]


@dataclass
class Universe:
    """A named set of symbols to screen, with the bars backing them."""

    name: str
    bars_by_symbol: dict[str, list[Bar]] = field(default_factory=dict)

    def symbols(self) -> list[str]:
        return sorted(self.bars_by_symbol)
