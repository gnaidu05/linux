#!/usr/bin/env bash
# Stop the SecureOS cloud VM and the noVNC proxy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-$SCRIPT_DIR/state}"

if [[ -f "$STATE_DIR/qemu.pid" ]]; then
    pid="$(cat "$STATE_DIR/qemu.pid")"
    if kill -0 "$pid" 2>/dev/null; then
        echo "[cloud] Sending ACPI powerdown to VM (pid $pid) ..."
        # Graceful shutdown via QMP if possible, else SIGTERM
        if [[ -S "$STATE_DIR/qmp.sock" ]] && command -v python3 >/dev/null; then
            python3 - "$STATE_DIR/qmp.sock" <<'PYEOF' || kill "$pid"
import json, socket, sys
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])
f = s.makefile("rw"); json.loads(f.readline())
for c in ({"execute": "qmp_capabilities"}, {"execute": "system_powerdown"}):
    f.write(json.dumps(c) + "\n"); f.flush(); json.loads(f.readline())
PYEOF
        else
            kill "$pid"
        fi
        for _ in $(seq 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
        kill -0 "$pid" 2>/dev/null && { echo "[cloud] Forcing off ..."; kill -9 "$pid"; }
    fi
    rm -f "$STATE_DIR/qemu.pid"
fi

pkill -f "websockify.*--web" 2>/dev/null || true
echo "[cloud] Stopped."
