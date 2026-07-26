"""Service configuration.

Loaded from a JSON file so the running service can be reconfigured without
editing code. Every field has a default that is safe to run unattended.

There is no field for an API key, a broker, or an account, because there is no
code in this package that could use one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "LTC-USD", "LINK-USD"]


@dataclass
class ServiceConfig:
    """Everything the 24/7 service needs to run one cycle, and how often to."""

    symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    granularity: int = 3600
    """Bar size in seconds. The service does useful work once per bar, so the
    cycle interval should divide into this."""
    interval_seconds: int = 300
    """How often to wake up. Cycles that find no newly closed bar do nothing
    except refresh the heartbeat."""
    state_dir: str = "/var/lib/quantlab"
    paper_initial_cash: float = 100_000.0
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    entry_window: int = 20
    exit_window: int = 10
    equity_fraction: float = 0.2
    alert_min_score: float = 0.75
    alert_drawdown_limit: float = 5_000.0
    scan_top_n: int = 5
    request_timeout: float = 20.0
    max_backoff_seconds: int = 900

    @classmethod
    def load(cls, path: str | Path) -> "ServiceConfig":
        """Read a config file, falling back to defaults for absent keys."""
        data = json.loads(Path(path).read_text())
        known = {f for f in cls().__dict__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path}: unknown config key(s): {', '.join(sorted(unknown))}")
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)

    def timeframe_label(self) -> str:
        from .feed import GRANULARITIES

        return GRANULARITIES.get(self.granularity, f"{self.granularity}s")
