"""The 24/7 supervisor loop.

Run it directly::

    python -m quantlab.live.service --config /etc/quantlab/config.json
    python -m quantlab.live.service --once          # one cycle, then exit

The loop is intentionally boring. It wakes on an interval, runs one cycle,
writes a heartbeat, and sleeps again. A cycle that raises is logged and backed
off exponentially up to ``max_backoff_seconds`` rather than killing the process,
because the common failure — the venue being briefly unreachable — is one the
next cycle fixes by itself. SIGTERM and SIGINT stop the loop after the cycle in
flight finishes, so systemd restarts and Ctrl-C never interrupt a state write.

For actual 24/7 operation, run it under the systemd unit in ``deploy/`` rather
than in a terminal: the unit restarts it on failure and on reboot, which a
shell loop does not.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import ServiceConfig
from .runner import run_cycle
from .store import Store

log = logging.getLogger("quantlab.service")

HEALTH_FILE = "health.json"


class Supervisor:
    """Runs cycles on an interval until asked to stop."""

    def __init__(self, config: ServiceConfig, store: Store) -> None:
        self.config = config
        self.store = store
        self.stopping = False
        self.consecutive_failures = 0

    def request_stop(self, signum, _frame) -> None:
        log.info("received signal %s, finishing current cycle then stopping", signum)
        self.stopping = True

    def _write_health(self, ok: bool, detail: str) -> None:
        self.store.write_json(
            HEALTH_FILE,
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "ok": ok,
                "detail": detail,
                "consecutive_failures": self.consecutive_failures,
                "mode": "paper",
                "live_order_routing": False,
            },
        )

    def run_one(self) -> bool:
        """Run a single cycle. Returns True on success."""
        try:
            result = run_cycle(self.config, self.store)
        except Exception as exc:  # keep the service alive across transient faults
            self.consecutive_failures += 1
            log.exception("cycle failed (%s consecutive)", self.consecutive_failures)
            self._write_health(False, f"{type(exc).__name__}: {exc}")
            return False
        self.consecutive_failures = 0
        log.info("%s", result.summary())
        for alert in result.alerts:
            log.warning("ALERT %s", alert.render().replace("\n", " | "))
        self._write_health(True, result.summary())
        return True

    def sleep_seconds(self) -> int:
        """Normal interval, or an exponential backoff after failures."""
        if not self.consecutive_failures:
            return self.config.interval_seconds
        backoff = self.config.interval_seconds * (2 ** min(self.consecutive_failures, 8))
        return min(backoff, self.config.max_backoff_seconds)

    def run_forever(self) -> int:
        log.info(
            "starting: %d symbols, %ds bars, %ds interval, state=%s, mode=PAPER "
            "(no broker connected)",
            len(self.config.symbols),
            self.config.granularity,
            self.config.interval_seconds,
            self.store.root,
        )
        while not self.stopping:
            self.run_one()
            if self.stopping:
                break
            deadline = time.monotonic() + self.sleep_seconds()
            while not self.stopping and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))
        log.info("stopped cleanly")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quantlab-service",
        description="24/7 paper-trading research service. Never places real orders.",
    )
    parser.add_argument("--config", type=Path, help="path to a JSON config file")
    parser.add_argument("--state-dir", type=Path, help="override the state directory")
    parser.add_argument("--once", action="store_true", help="run one cycle and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        stream=sys.stdout,
    )

    config = ServiceConfig.load(args.config) if args.config else ServiceConfig()
    if args.state_dir:
        config.state_dir = str(args.state_dir)
    store = Store(config.state_dir)
    store.write_json("config_in_use.json", config.to_dict())

    supervisor = Supervisor(config, store)
    if args.once:
        return 0 if supervisor.run_one() else 1

    signal.signal(signal.SIGTERM, supervisor.request_stop)
    signal.signal(signal.SIGINT, supervisor.request_stop)
    return supervisor.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
