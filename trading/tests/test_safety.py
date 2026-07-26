"""Constraints that must hold for the whole package, enforced as tests.

These are the promises in the README, checked mechanically so they cannot rot.
The package now reaches the network for market data, so the invariants are
stated precisely:

* **No credentials, anywhere.** Not in the core, not in the live layer.
* **No order routing, anywhere.** Nothing that could place, modify, or cancel an
  order at a venue.
* **Network access is confined to one file**, ``quantlab/live/feed.py``, and
  that file is read-only: GET requests to a public endpoint, no auth header, no
  request body.

The research core — data, indicators, scanner, backtest, journal, news, alerts —
stays completely network-free, so a backtest or a journal run cannot depend on
anything outside the machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "quantlab"
SOURCES = sorted(PACKAGE.rglob("*.py"))

NETWORK_FILE = PACKAGE / "live" / "feed.py"
OFFLINE_SOURCES = [p for p in SOURCES if p != NETWORK_FILE]

NETWORK_TOKENS = [
    "import requests",
    "import urllib",
    "import http.client",
    "import socket",
    "import websocket",
    "urlopen",
    "ccxt",
]

CREDENTIAL_TOKENS = [
    "api_key",
    "api_secret",
    "apikey",
    "secret_key",
    "private_key",
    "passphrase",
    "access_token",
    "authorization",
    "bearer ",
    "hmac",
    "signature",
]

EXECUTION_TOKENS = [
    "place_order",
    "submit_order",
    "create_order",
    "cancel_order",
    "amend_order",
    "live_trade",
]


def test_sources_were_found():
    assert len(SOURCES) >= 20


@pytest.mark.parametrize("path", OFFLINE_SOURCES, ids=lambda p: p.name)
def test_only_the_feed_module_touches_the_network(path):
    """Everything except quantlab/live/feed.py must be network-free."""
    text = path.read_text()
    for token in NETWORK_TOKENS:
        assert token not in text, f"{path.name} contains {token!r}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_credential_handling_anywhere_in_the_package(path):
    text = path.read_text().lower()
    for token in CREDENTIAL_TOKENS:
        assert token not in text, f"{path.name} contains {token!r}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_live_order_routing_anywhere_in_the_package(path):
    text = path.read_text().lower()
    for token in EXECUTION_TOKENS:
        assert token not in text, f"{path.name} contains {token!r}"


def test_the_research_core_is_entirely_offline():
    """A backtest or journal run must not be able to depend on the network."""
    core = ["data", "scanner", "backtest", "journal", "news", "alerts"]
    for name in core:
        for path in (PACKAGE / name).rglob("*.py"):
            text = path.read_text()
            for token in NETWORK_TOKENS:
                assert token not in text, f"core module {path.name} contains {token!r}"
    for token in NETWORK_TOKENS:
        assert token not in (PACKAGE / "indicators.py").read_text()


def test_the_feed_issues_no_write_requests():
    """The one networked file must only ever read."""
    text = NETWORK_FILE.read_text()
    for verb in ('"POST"', '"PUT"', '"DELETE"', '"PATCH"', "data=", "json=payload"):
        assert verb not in text, f"feed.py contains {verb!r}"
    assert 'method="GET"' in text


def test_no_module_claims_to_predict_price():
    """No public API should promise a forecast or a probability of profit."""
    banned = ("predict_price", "forecast_return", "probability_of_profit", "win_probability")
    for path in SOURCES:
        text = path.read_text().lower()
        for token in banned:
            assert f"def {token}" not in text, f"{path.name} defines {token!r}"


def test_service_status_declares_paper_mode():
    """The heartbeat must always say order routing is off."""
    text = (PACKAGE / "live" / "runner.py").read_text()
    assert '"live_order_routing": False' in text
    assert '"mode": "paper"' in text


def test_limitations_document_exists_and_covers_the_named_biases():
    doc = (PACKAGE.parent / "LIMITATIONS.md").read_text().lower()
    for topic in ("look-ahead", "survivorship", "overfitting", "slippage", "sharpe",
                  "paper", "partial candle"):
        assert topic in doc, f"LIMITATIONS.md does not discuss {topic}"
