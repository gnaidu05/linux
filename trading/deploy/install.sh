#!/usr/bin/env bash
# Install the quantlab service for 24/7 operation under systemd.
#
# Idempotent: safe to re-run to deploy an updated copy of the code.
#
# The service runs paper simulation only. It reads a public market-data
# endpoint and writes JSON to /var/lib/quantlab. It has no broker account,
# no credentials, and no way to place an order.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/quantlab
CONFIG_DIR=/etc/quantlab
UNIT=/etc/systemd/system/quantlab.service

if [[ $EUID -ne 0 ]]; then
    echo "error: run as root (needs to write $PREFIX, $CONFIG_DIR and $UNIT)" >&2
    exit 1
fi

if ! command -v python3 >/dev/null; then
    echo "error: python3 not found" >&2
    exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"error: python 3.11+ required, found {sys.version.split()[0]}")
PY

echo "==> installing code to $PREFIX"
install -d -m 0755 "$PREFIX"
rm -rf "$PREFIX/quantlab"
cp -r "$SRC/quantlab" "$PREFIX/quantlab"
find "$PREFIX/quantlab" -name __pycache__ -type d -prune -exec rm -rf {} +
install -m 0644 "$SRC/README.md" "$PREFIX/README.md"
install -m 0644 "$SRC/LIMITATIONS.md" "$PREFIX/LIMITATIONS.md"

echo "==> installing config to $CONFIG_DIR"
install -d -m 0755 "$CONFIG_DIR"
if [[ -f "$CONFIG_DIR/config.json" ]]; then
    echo "    config.json already exists, leaving it alone"
else
    install -m 0644 "$SRC/deploy/config.example.json" "$CONFIG_DIR/config.json"
fi

echo "==> verifying the service can run a cycle"
PYTHONPATH="$PREFIX" python3 -m quantlab.live.service \
    --config "$CONFIG_DIR/config.json" --once --log-level INFO

echo "==> installing unit $UNIT"
install -m 0644 "$SRC/deploy/quantlab.service" "$UNIT"
systemctl daemon-reload
systemctl enable --now quantlab.service

echo
echo "installed. paper simulation only — no broker is connected."
echo "  status:   systemctl status quantlab"
echo "  logs:     journalctl -u quantlab -f"
echo "  state:    /var/lib/quantlab/status.json"
