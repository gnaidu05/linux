"""Advisory alert layer.

Alerts are notifications that a rule you wrote became true. They are advisory:
this module has no broker connection, no credentials, and no code path that
places, modifies, or cancels an order. Composing a scan hit with a news tag does
not make either one predictive; it makes one message instead of two.

Every alert carries the evidence that triggered it so it can be checked before
it is acted on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..journal.stats import Stats
from ..news.aggregator import NewsDigest
from ..scanner.engine import ScanReport, ScanResult

ADVISORY_NOTICE = (
    "Advisory only. This is a rule firing on past data, not a recommendation, "
    "a forecast, or an order."
)


@dataclass(frozen=True)
class Alert:
    """One rule that fired, with the evidence behind it."""

    ts: datetime
    kind: str
    subject: str
    message: str
    evidence: list[str]

    def render(self) -> str:
        lines = [f"[{self.kind}] {self.subject} @ {self.ts.isoformat()}", self.message]
        lines.extend(f"  - {e}" for e in self.evidence)
        lines.append(f"  {ADVISORY_NOTICE}")
        return "\n".join(lines)


def scan_threshold_alerts(
    report: ScanReport, *, min_score: float, digest: NewsDigest | None = None
) -> list[Alert]:
    """Alert on every scan result at or above ``min_score``.

    When a ``digest`` is supplied, headlines tagged with the same symbol are
    attached as context to read. They do not change the score and do not
    contribute to whether the alert fires.
    """
    by_asset = digest.by_asset() if digest else {}
    alerts = []
    for result in report.results:
        if result.score < min_score:
            continue
        evidence = [
            f"{c.name}: score {c.score:.3f} (weight {c.weight:.2f}) from "
            + ", ".join(f"{k}={v:.6g}" for k, v in c.inputs.items())
            for c in result.components
        ]
        for headline in by_asset.get(result.symbol, []):
            evidence.append(f"context (not scored): {headline.source} - {headline.title} {headline.url}")
        alerts.append(
            Alert(
                ts=report.asof,
                kind="scan",
                subject=result.symbol,
                message=(
                    f"Scan score {result.score:.3f} >= threshold {min_score:.3f} "
                    f"in universe {report.universe!r}. Score measures rule match, "
                    "not expected return."
                ),
                evidence=evidence,
            )
        )
    return alerts


def drawdown_alert(stats: Stats, *, limit: float, ts: datetime) -> Alert | None:
    """Alert when realized closed-trade drawdown exceeds ``limit`` in currency."""
    if stats.max_drawdown < limit:
        return None
    return Alert(
        ts=ts,
        kind="risk",
        subject="journal",
        message=(
            f"Closed-trade drawdown {stats.max_drawdown:,.2f} has reached the "
            f"limit of {limit:,.2f}."
        ),
        evidence=[
            f"{stats.n_trades} closed trades, win rate {stats.win_rate:.1%}",
            f"net realized P&L {stats.net_pnl:+,.2f}",
            "drawdown is measured on the closed-trade sequence, so it excludes "
            "open-position pain",
        ],
    )


def scan_result_summary(result: ScanResult) -> str:
    """Full arithmetic behind one scan result, for pasting into a notification."""
    return result.explain()
