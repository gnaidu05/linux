from datetime import datetime, timedelta, timezone

import pytest

from quantlab.alerts.rules import ADVISORY_NOTICE, drawdown_alert, scan_threshold_alerts
from quantlab.data.sources import synthetic_bars
from quantlab.journal.stats import compute_stats
from quantlab.news.aggregator import aggregate
from quantlab.news.models import Headline
from quantlab.scanner.criteria import Universe
from quantlab.scanner.engine import Scanner
from tests.test_journal import trade

T0 = datetime(2024, 5, 1, tzinfo=timezone.utc)


@pytest.fixture
def report():
    universe = Universe(
        "u", {s: synthetic_bars(s, 300, seed=i) for i, s in enumerate(["AAA", "BBB", "CCC"])}
    )
    return Scanner().scan(universe, universe.bars_by_symbol["AAA"][-1].ts)


def test_alerts_fire_only_at_or_above_the_threshold(report):
    cutoff = sorted(r.score for r in report.results)[-1]
    alerts = scan_threshold_alerts(report, min_score=cutoff)
    assert len(alerts) == 1
    assert alerts[0].subject == report.results[0].symbol


def test_no_alerts_when_nothing_clears_the_threshold(report):
    assert scan_threshold_alerts(report, min_score=1.01) == []


def test_every_component_appears_as_evidence(report):
    alert = scan_threshold_alerts(report, min_score=0.0)[0]
    top = report.results[0]
    evidence = "\n".join(alert.evidence)
    for comp in top.components:
        assert comp.name in evidence
        for key in comp.inputs:
            assert key in evidence


def test_rendered_alert_carries_the_advisory_notice(report):
    text = scan_threshold_alerts(report, min_score=0.0)[0].render()
    assert ADVISORY_NOTICE in text
    assert "not a recommendation" in text


def test_alert_message_says_the_score_is_not_expected_return(report):
    alert = scan_threshold_alerts(report, min_score=0.0)[0]
    assert "not expected return" in alert.message


def test_news_context_is_attached_but_labelled_as_unscored(report):
    symbol = report.results[0].symbol
    digest = aggregate(
        [Headline("wire", f"{symbol} in the news", "https://example.invalid/1", T0)],
        {symbol: [symbol]},
    )
    with_news = scan_threshold_alerts(report, min_score=0.0, digest=digest)[0]
    without_news = scan_threshold_alerts(report, min_score=0.0)[0]
    assert any("context (not scored)" in e for e in with_news.evidence)
    # News changes the evidence shown, never the score that triggered the alert.
    assert with_news.message == without_news.message


def test_drawdown_alert_fires_at_the_limit():
    stats = compute_stats([trade(100.0), trade(-60.0)])
    assert drawdown_alert(stats, limit=60.0, ts=T0) is not None
    assert drawdown_alert(stats, limit=60.01, ts=T0) is None


def test_drawdown_alert_states_what_the_measure_excludes():
    stats = compute_stats([trade(100.0), trade(-60.0)])
    text = drawdown_alert(stats, limit=10.0, ts=T0).render()
    assert "excludes" in text and "open-position pain" in text
    assert ADVISORY_NOTICE in text


def test_alerts_module_has_no_order_placement_surface():
    """The alert layer must not grow an execution path."""
    import inspect

    from quantlab.alerts import rules

    source = inspect.getsource(rules).lower()
    for banned in ("api_key", "api_secret", "place_order", "submit_order", "requests.", "urllib"):
        assert banned not in source, f"alert layer references {banned!r}"
