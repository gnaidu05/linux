"""One service cycle: fetch, screen, paper-trade, journal, alert, persist.

A cycle is idempotent with respect to bars it has already seen. Waking up more
often than the bar size just refreshes the heartbeat; the paper broker only acts
on bars that closed since the last cycle, so a restart loop cannot double-trade
a bar or replay one that already filled.

Everything a cycle produces lands in the state directory as readable JSON. The
service has no other output surface — no orders, no messages to a venue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..alerts.rules import Alert, drawdown_alert, scan_threshold_alerts
from ..backtest.execution import ExecutionModel
from ..data.types import Bar
from ..journal.stats import JournalReport, build_journal
from ..scanner.criteria import Universe
from ..scanner.engine import ScanReport, Scanner
from ..strategies import DonchianBreakout
from .config import ServiceConfig
from .feed import fetch_universe
from .paper import (
    EQUITY_FILE,
    FILLS_FILE,
    STATE_FILE,
    PaperBroker,
    PaperCycle,
    PaperState,
    fill_from_dict,
    fill_to_dict,
)
from .store import Store

ALERTS_FILE = "alerts.jsonl"
SCAN_FILE = "scan_latest.json"
STATUS_FILE = "status.json"

FetchFn = Callable[..., tuple[dict[str, list[Bar]], dict[str, str]]]


@dataclass(frozen=True)
class CycleResult:
    """What one cycle did, for the status file and for tests."""

    ts: datetime
    symbols_ok: list[str]
    symbols_failed: dict[str, str]
    scan: ScanReport | None
    paper: PaperCycle
    journal: JournalReport
    alerts: list[Alert]

    def summary(self) -> str:
        top = (
            ", ".join(f"{r.symbol} {r.score:.3f}" for r in self.scan.top(3))
            if self.scan
            else "no scan"
        )
        return (
            f"{self.ts.isoformat()} ok={len(self.symbols_ok)} "
            f"failed={len(self.symbols_failed)} bars={self.paper.bars_processed} "
            f"fills={len(self.paper.fills)} equity={self.paper.equity:,.2f} "
            f"alerts={len(self.alerts)} top=[{top}]"
        )


def _alert_to_dict(alert: Alert) -> dict:
    return {
        "ts": alert.ts.isoformat(),
        "kind": alert.kind,
        "subject": alert.subject,
        "message": alert.message,
        "evidence": alert.evidence,
    }


def run_cycle(
    config: ServiceConfig,
    store: Store,
    *,
    fetch: FetchFn = fetch_universe,
    now: datetime | None = None,
) -> CycleResult:
    """Run one full cycle and persist everything it produced."""
    now = now or datetime.now(timezone.utc)
    execution = ExecutionModel(fee_bps=config.fee_bps, slippage_bps=config.slippage_bps)

    bars, errors = fetch(
        config.symbols,
        granularity=config.granularity,
        timeout=config.request_timeout,
        now=now,
    )
    usable = {sym: b for sym, b in bars.items() if b}

    scanner = Scanner()
    scan: ScanReport | None = None
    if usable:
        asof = max(b[-1].ts for b in usable.values())
        scan = scanner.scan(Universe(name="live", bars_by_symbol=usable), asof)

    state_row = store.read_json(STATE_FILE)
    state = (
        PaperState.from_dict(state_row)
        if state_row
        else PaperState(cash=config.paper_initial_cash)
    )
    broker = PaperBroker(state, execution)
    strategy = DonchianBreakout(
        entry_window=config.entry_window,
        exit_window=config.exit_window,
        equity_fraction=config.equity_fraction,
        timeframe=config.timeframe_label(),
    )
    paper = broker.advance(usable, strategy)

    store.write_json(STATE_FILE, broker.state.to_dict())
    store.append_jsonl(FILLS_FILE, [fill_to_dict(f) for f in paper.fills])
    if paper.bars_processed:
        store.append_jsonl(
            EQUITY_FILE, [{"ts": now.isoformat(), "equity": paper.equity}]
        )

    all_fills = [fill_from_dict(row) for row in store.read_jsonl(FILLS_FILE)]
    journal = build_journal(all_fills)

    alerts: list[Alert] = []
    if scan:
        alerts.extend(
            scan_threshold_alerts(scan, min_score=config.alert_min_score)
        )
    dd = drawdown_alert(journal.overall, limit=config.alert_drawdown_limit, ts=now)
    if dd:
        alerts.append(dd)
    store.append_jsonl(ALERTS_FILE, [_alert_to_dict(a) for a in alerts])

    if scan:
        store.write_json(
            SCAN_FILE,
            {
                "asof": scan.asof.isoformat(),
                "universe": scan.universe,
                "skipped": [{"symbol": s.symbol, "reason": s.reason} for s in scan.skipped],
                "results": [
                    {
                        "symbol": r.symbol,
                        "score": r.score,
                        "components": [
                            {
                                "name": c.name,
                                "score": c.score,
                                "weight": c.weight,
                                "formula": c.formula,
                                "inputs": c.inputs,
                            }
                            for c in r.components
                        ],
                    }
                    for r in scan.top(config.scan_top_n)
                ],
            },
        )

    result = CycleResult(
        ts=now,
        symbols_ok=sorted(usable),
        symbols_failed=errors,
        scan=scan,
        paper=paper,
        journal=journal,
        alerts=alerts,
    )
    store.write_json(STATUS_FILE, build_status(config, result, broker.state))
    return result


def build_status(
    config: ServiceConfig, result: CycleResult, state: PaperState
) -> dict:
    """The heartbeat document, written after every cycle.

    Read this to see whether the service is alive and what it last did. The
    disclaimers are part of the payload so they travel with the numbers into
    whatever reads them.
    """
    return {
        "last_cycle_ts": result.ts.isoformat(),
        "mode": "paper",
        "live_order_routing": False,
        "symbols_ok": result.symbols_ok,
        "symbols_failed": result.symbols_failed,
        "granularity_seconds": config.granularity,
        "bars_processed_this_cycle": result.paper.bars_processed,
        "fills_this_cycle": len(result.paper.fills),
        "alerts_this_cycle": len(result.alerts),
        "paper": {
            "started_at": state.started_at,
            "last_bar_ts": state.last_ts,
            "cash": state.cash,
            "positions": state.positions,
            "pending_orders": len(state.pending),
            "equity": result.paper.equity,
            "initial_cash": config.paper_initial_cash,
        },
        "journal": {
            "closed_trades": result.journal.overall.n_trades,
            "win_rate": result.journal.overall.win_rate,
            "net_pnl": result.journal.overall.net_pnl,
            "expectancy": result.journal.overall.expectancy,
            "max_drawdown": result.journal.overall.max_drawdown,
        },
        "top_scan": (
            [
                {"symbol": r.symbol, "score": r.score}
                for r in result.scan.top(config.scan_top_n)
            ]
            if result.scan
            else []
        ),
        "disclaimers": [
            "Paper simulation only. No broker or exchange account is connected "
            "and no order has been sent anywhere.",
            "Fills are what the fill model says would have happened, not what a "
            "venue confirmed.",
            "Scan scores measure rule match, not expected return, and are not a "
            "probability of profit.",
            "The paper record starts when the service started; it is a small "
            "forward sample of one path.",
        ],
    }
