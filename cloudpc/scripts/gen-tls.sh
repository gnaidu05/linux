#!/usr/bin/env bash
# Generate a self-signed TLS certificate for testing.
# For production use Let's Encrypt — see README.md ("TLS in production").
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TLS_DIR="$SCRIPT_DIR/../secrets/tls"
CN="${1:-cloudpc.local}"

mkdir -p "$TLS_DIR"
openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -days 825 \
    -subj "/CN=$CN" \
    -addext "subjectAltName=DNS:$CN,DNS:localhost,IP:127.0.0.1" \
    -keyout "$TLS_DIR/privkey.pem" -out "$TLS_DIR/fullchain.pem" 2>/dev/null
chmod 600 "$TLS_DIR/privkey.pem"
echo "[tls] Self-signed certificate written to secrets/tls/ (CN=$CN)"
