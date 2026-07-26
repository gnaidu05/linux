"""Constraints that must hold for the whole package, enforced as tests.

These are the promises in the README, checked mechanically so they cannot rot:
the toolkit cannot reach a broker, cannot hold credentials, and does not emit a
directional call or a probability of profit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "quantlab"
SOURCES = sorted(PACKAGE.rglob("*.py"))

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
    assert len(SOURCES) >= 15


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_network_client_anywhere_in_the_package(path):
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


def test_no_module_claims_to_predict_price():
    """No public API should promise a forecast or a probability of profit."""
    banned = ("predict_price", "forecast_return", "probability_of_profit", "win_probability")
    for path in SOURCES:
        text = path.read_text().lower()
        for token in banned:
            assert f"def {token}" not in text, f"{path.name} defines {token!r}"


def test_limitations_document_exists_and_covers_the_named_biases():
    doc = (PACKAGE.parent / "LIMITATIONS.md").read_text().lower()
    for topic in ("look-ahead", "survivorship", "overfitting", "slippage", "sharpe"):
        assert topic in doc, f"LIMITATIONS.md does not discuss {topic}"
