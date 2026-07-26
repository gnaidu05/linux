"""The scan itself: run criteria over a universe and rank the results.

The output is a ranking of how well each instrument matches a written set of
rules at a point in time. It is not a forecast, and the score has no units of
expected return, probability, or confidence. Two instruments with scores 0.81
and 0.42 differ in how many rules they match and by how much — nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..data.types import Bar, as_of
from .criteria import Component, Criterion, Universe, default_criteria


@dataclass(frozen=True)
class ScanResult:
    """One instrument's score at one point in time, with its decomposition."""

    symbol: str
    asof: datetime
    score: float
    components: list[Component]

    def explain(self) -> str:
        """Render the full arithmetic behind ``score`` as plain text."""
        lines = [f"{self.symbol} @ {self.asof.isoformat()}  score={self.score:.4f}"]
        total_weight = sum(c.weight for c in self.components)
        for c in self.components:
            lines.append(
                f"  {c.name:<12} score={c.score:.4f} weight={c.weight:.2f} "
                f"contribution={c.contribution / total_weight:.4f}"
            )
            lines.append(f"      formula: {c.formula}")
            for k, v in c.inputs.items():
                lines.append(f"      {k} = {v:.6g}")
        lines.append(f"  total = sum(contributions) / total_weight({total_weight:.2f})")
        return "\n".join(lines)


@dataclass(frozen=True)
class SkippedSymbol:
    """A symbol that could not be scored, and why."""

    symbol: str
    reason: str


@dataclass(frozen=True)
class ScanReport:
    """Everything one scan produced, including what it could not score."""

    universe: str
    asof: datetime
    results: list[ScanResult]
    skipped: list[SkippedSymbol]

    def top(self, n: int) -> list[ScanResult]:
        return self.results[:n]


class Scanner:
    """Rules-based screen over a universe of instruments."""

    def __init__(self, criteria: list[Criterion] | None = None) -> None:
        self.criteria = criteria if criteria is not None else default_criteria()
        self.min_bars = max(c.min_bars() for c in self.criteria)

    def scan_symbol(self, symbol: str, bars: list[Bar], asof: datetime) -> ScanResult:
        """Score one symbol using only bars that had closed by ``asof``."""
        visible = as_of(bars, asof)
        components = [c.evaluate(visible) for c in self.criteria]
        total_weight = sum(c.weight for c in components)
        score = sum(c.contribution for c in components) / total_weight
        return ScanResult(symbol=symbol, asof=asof, score=score, components=components)

    def scan(self, universe: Universe, asof: datetime) -> ScanReport:
        """Score and rank every symbol in ``universe`` as of ``asof``.

        Symbols without enough closed bars are skipped and reported rather than
        scored on partial data, so a thin listing cannot quietly rank highly.
        """
        results: list[ScanResult] = []
        skipped: list[SkippedSymbol] = []
        for symbol in universe.symbols():
            bars = universe.bars_by_symbol[symbol]
            visible = as_of(bars, asof)
            if len(visible) < self.min_bars:
                skipped.append(
                    SkippedSymbol(
                        symbol,
                        f"needs {self.min_bars} closed bars, has {len(visible)} at {asof.isoformat()}",
                    )
                )
                continue
            results.append(self.scan_symbol(symbol, bars, asof))
        results.sort(key=lambda r: (-r.score, r.symbol))
        return ScanReport(
            universe=universe.name, asof=asof, results=results, skipped=skipped
        )
