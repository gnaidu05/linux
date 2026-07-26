"""Runner, store, and supervisor tests. No network: the feed is injected."""

from datetime import datetime, timedelta, timezone

import pytest

from quantlab.data.sources import synthetic_bars
from quantlab.live.config import ServiceConfig
from quantlab.live.feed import FeedError
from quantlab.live.paper import FILLS_FILE, STATE_FILE
from quantlab.live.runner import ALERTS_FILE, SCAN_FILE, STATUS_FILE, run_cycle
from quantlab.live.service import HEALTH_FILE, Supervisor
from quantlab.live.store import Store

NOW = datetime(2024, 6, 1, tzinfo=timezone.utc)
SYMBOLS = ["AAA", "BBB", "CCC"]


def make_config(tmp_path, **kw):
    return ServiceConfig(
        symbols=list(SYMBOLS),
        state_dir=str(tmp_path / "state"),
        interval_seconds=1,
        **kw,
    )


def feeder(n_bars=400, failures=None, seed_offset=0):
    """A fetch function that serves deterministic synthetic bars."""

    def fetch(symbols, *, granularity, timeout, now):
        bars, errors = {}, dict(failures or {})
        for i, sym in enumerate(symbols):
            if sym in errors:
                continue
            bars[sym] = synthetic_bars(
                sym, n_bars, seed=i + 1 + seed_offset, start=NOW,
                step=timedelta(seconds=granularity),
            )
        return bars, errors

    return fetch


# --- store -------------------------------------------------------------------


def test_store_creates_its_directory(tmp_path):
    store = Store(tmp_path / "nested" / "state")
    assert store.root.is_dir()


def test_write_json_replaces_atomically_and_leaves_no_temp_file(tmp_path):
    store = Store(tmp_path)
    store.write_json("a.json", {"v": 1})
    store.write_json("a.json", {"v": 2})
    assert store.read_json("a.json") == {"v": 2}
    assert list(store.root.glob("*.tmp")) == []


def test_read_json_returns_the_default_when_absent(tmp_path):
    assert Store(tmp_path).read_json("nope.json", default={"d": 1}) == {"d": 1}


def test_jsonl_appends_accumulate(tmp_path):
    store = Store(tmp_path)
    store.append_jsonl("log.jsonl", [{"i": 1}, {"i": 2}])
    store.append_jsonl("log.jsonl", [{"i": 3}])
    assert [r["i"] for r in store.read_jsonl("log.jsonl")] == [1, 2, 3]


def test_appending_nothing_does_not_create_a_file(tmp_path):
    store = Store(tmp_path)
    store.append_jsonl("log.jsonl", [])
    assert not store.path("log.jsonl").exists()


# --- config ------------------------------------------------------------------


def test_config_loads_from_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"symbols": ["X"], "interval_seconds": 60}')
    config = ServiceConfig.load(p)
    assert config.symbols == ["X"]
    assert config.interval_seconds == 60
    assert config.granularity == 3600  # default preserved


def test_config_rejects_unknown_keys(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"api_secret": "hunter2"}')
    with pytest.raises(ValueError, match="unknown config key"):
        ServiceConfig.load(p)


def test_config_has_no_credential_or_account_fields():
    fields = set(ServiceConfig().__dict__)
    for banned in ("key", "secret", "token", "account", "broker", "exchange"):
        assert not any(banned in f for f in fields), f"config exposes {banned}"


def test_timeframe_label_matches_the_granularity():
    assert ServiceConfig(granularity=3600).timeframe_label() == "1h"
    assert ServiceConfig(granularity=86400).timeframe_label() == "1d"


# --- one cycle ---------------------------------------------------------------


def test_cycle_scans_every_symbol_it_fetched(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    result = run_cycle(config, store, fetch=feeder(), now=NOW)
    assert result.symbols_ok == sorted(SYMBOLS)
    assert result.scan is not None
    assert {r.symbol for r in result.scan.results} == set(SYMBOLS)


def test_first_cycle_is_a_bootstrap_with_no_fills(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    result = run_cycle(config, store, fetch=feeder(), now=NOW)
    assert result.paper.bootstrapped is True
    assert result.paper.fills == []
    assert result.journal.overall.n_trades == 0


def test_a_failing_symbol_does_not_stop_the_cycle(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    result = run_cycle(
        config, store, fetch=feeder(failures={"BBB": "HTTP 503"}), now=NOW
    )
    assert result.symbols_ok == ["AAA", "CCC"]
    assert result.symbols_failed == {"BBB": "HTTP 503"}
    assert result.scan is not None


def test_a_cycle_with_no_data_at_all_still_writes_a_status(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)

    def dead(symbols, **kw):
        return {}, {s: "unreachable" for s in symbols}

    result = run_cycle(config, store, fetch=dead, now=NOW)
    assert result.scan is None
    assert store.read_json(STATUS_FILE)["symbols_ok"] == []


def test_cycle_persists_state_scan_and_status(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    run_cycle(config, store, fetch=feeder(), now=NOW)
    assert store.read_json(STATE_FILE) is not None
    assert store.read_json(SCAN_FILE)["results"]
    assert store.read_json(STATUS_FILE)["last_cycle_ts"] == NOW.isoformat()


def test_persisted_scan_keeps_the_full_component_decomposition(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    run_cycle(config, store, fetch=feeder(), now=NOW)
    top = store.read_json(SCAN_FILE)["results"][0]
    assert {c["name"] for c in top["components"]} == {
        "trend", "volume", "volatility", "structure"
    }
    for component in top["components"]:
        assert component["formula"]
        assert component["inputs"]


def test_status_declares_paper_mode_and_carries_disclaimers(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    run_cycle(config, store, fetch=feeder(), now=NOW)
    status = store.read_json(STATUS_FILE)
    assert status["mode"] == "paper"
    assert status["live_order_routing"] is False
    joined = " ".join(status["disclaimers"]).lower()
    assert "no order has been sent anywhere" in joined
    assert "not a probability of profit" in joined


def test_later_cycles_trade_and_accumulate_fills(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    run_cycle(config, store, fetch=feeder(n_bars=300), now=NOW)
    for extra in range(1, 6):
        run_cycle(
            config, store, fetch=feeder(n_bars=300 + extra * 20), now=NOW
        )
    fills = store.read_jsonl(FILLS_FILE)
    assert fills, "expected the paper broker to trade once new bars arrived"
    assert all(set(f) >= {"ts", "symbol", "side", "qty", "price", "fee"} for f in fills)


def test_journal_reflects_accumulated_paper_fills(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    run_cycle(config, store, fetch=feeder(n_bars=300), now=NOW)
    result = None
    for extra in range(1, 8):
        result = run_cycle(config, store, fetch=feeder(n_bars=300 + extra * 25), now=NOW)
    assert result.journal.overall.n_trades >= 0
    assert len(store.read_jsonl(FILLS_FILE)) >= result.journal.overall.n_trades


def test_repeated_cycles_on_identical_data_are_idempotent(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    run_cycle(config, store, fetch=feeder(n_bars=300), now=NOW)
    run_cycle(config, store, fetch=feeder(n_bars=320), now=NOW)
    fills_after_two = len(store.read_jsonl(FILLS_FILE))
    for _ in range(3):
        result = run_cycle(config, store, fetch=feeder(n_bars=320), now=NOW)
        assert result.paper.bars_processed == 0
    assert len(store.read_jsonl(FILLS_FILE)) == fills_after_two


def test_alerts_are_logged_when_the_threshold_is_cleared(tmp_path):
    config = make_config(tmp_path, alert_min_score=0.0)
    store = Store(config.state_dir)
    result = run_cycle(config, store, fetch=feeder(), now=NOW)
    assert len(result.alerts) == len(result.scan.results)
    assert len(store.read_jsonl(ALERTS_FILE)) == len(result.alerts)


def test_no_alerts_when_nothing_clears_the_threshold(tmp_path):
    config = make_config(tmp_path, alert_min_score=1.01, alert_drawdown_limit=1e12)
    store = Store(config.state_dir)
    result = run_cycle(config, store, fetch=feeder(), now=NOW)
    assert result.alerts == []


def test_cycle_summary_reports_counts(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    summary = run_cycle(config, store, fetch=feeder(), now=NOW).summary()
    assert "ok=3" in summary and "failed=0" in summary and "equity=" in summary


# --- supervisor --------------------------------------------------------------


def test_supervisor_writes_health_on_success(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    monkeypatch.setattr(
        "quantlab.live.service.run_cycle",
        lambda c, s: run_cycle(c, s, fetch=feeder(), now=NOW),
    )
    supervisor = Supervisor(config, store)
    assert supervisor.run_one() is True
    health = store.read_json(HEALTH_FILE)
    assert health["ok"] is True
    assert health["consecutive_failures"] == 0
    assert health["live_order_routing"] is False


def test_supervisor_survives_a_failing_cycle(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.state_dir)

    def boom(c, s):
        raise FeedError("venue unreachable")

    monkeypatch.setattr("quantlab.live.service.run_cycle", boom)
    supervisor = Supervisor(config, store)
    assert supervisor.run_one() is False
    health = store.read_json(HEALTH_FILE)
    assert health["ok"] is False
    assert "venue unreachable" in health["detail"]
    assert supervisor.consecutive_failures == 1


def test_backoff_grows_with_consecutive_failures_and_is_capped(tmp_path):
    config = make_config(tmp_path, max_backoff_seconds=60)
    config.interval_seconds = 5
    supervisor = Supervisor(config, Store(config.state_dir))
    assert supervisor.sleep_seconds() == 5
    supervisor.consecutive_failures = 1
    assert supervisor.sleep_seconds() == 10
    supervisor.consecutive_failures = 3
    assert supervisor.sleep_seconds() == 40
    supervisor.consecutive_failures = 20
    assert supervisor.sleep_seconds() == 60  # capped


def test_a_success_after_failures_resets_the_backoff(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    supervisor = Supervisor(config, store)
    supervisor.consecutive_failures = 4
    monkeypatch.setattr(
        "quantlab.live.service.run_cycle",
        lambda c, s: run_cycle(c, s, fetch=feeder(), now=NOW),
    )
    supervisor.run_one()
    assert supervisor.consecutive_failures == 0
    assert supervisor.sleep_seconds() == config.interval_seconds


def test_signal_handler_requests_a_graceful_stop(tmp_path):
    config = make_config(tmp_path)
    supervisor = Supervisor(config, Store(config.state_dir))
    assert supervisor.stopping is False
    supervisor.request_stop(15, None)
    assert supervisor.stopping is True


def test_run_forever_exits_promptly_once_stop_is_requested(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.state_dir)
    calls = []

    def one_then_stop(c, s):
        calls.append(1)
        supervisor.stopping = True
        return run_cycle(c, s, fetch=feeder(), now=NOW)

    monkeypatch.setattr("quantlab.live.service.run_cycle", one_then_stop)
    supervisor = Supervisor(config, store)
    assert supervisor.run_forever() == 0
    assert len(calls) == 1


def test_cli_once_runs_a_single_cycle(tmp_path, monkeypatch):
    from quantlab.live import service

    monkeypatch.setattr(
        service, "run_cycle", lambda c, s: run_cycle(c, s, fetch=feeder(), now=NOW)
    )
    code = service.main(["--once", "--state-dir", str(tmp_path / "s"), "--log-level", "ERROR"])
    assert code == 0
    assert Store(tmp_path / "s").read_json(STATUS_FILE) is not None


def test_cli_records_the_config_it_is_running_with(tmp_path, monkeypatch):
    from quantlab.live import service

    monkeypatch.setattr(
        service, "run_cycle", lambda c, s: run_cycle(c, s, fetch=feeder(), now=NOW)
    )
    service.main(["--once", "--state-dir", str(tmp_path / "s"), "--log-level", "ERROR"])
    assert Store(tmp_path / "s").read_json("config_in_use.json")["granularity"] == 3600
