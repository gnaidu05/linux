#!/usr/bin/env bash
#
# SecureOS cloud runner — boot the OS on a server and expose the desktop
# to any web browser via noVNC over HTTPS.
#
#   sudo ./cloud/run-cloud.sh --iso out/secureos-1.0-amd64.iso      # live boot
#   sudo ./cloud/run-cloud.sh --disk secureos.qcow2                 # boot installed disk
#   sudo ./cloud/run-cloud.sh --iso ... --disk secureos.qcow2       # boot ISO with disk
#                                                                   # attached (to install)
# Then open:  https://<server-ip>:6080/vnc.html
#
# Architecture:
#   browser ──HTTPS/WSS──> websockify+noVNC (public, TLS) ──> QEMU VNC
#                                                             (127.0.0.1 only,
#                                                              password-protected)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-$SCRIPT_DIR/state}"

# --- Tunables (env-overridable) --------------------------------------------
RAM_MB="${RAM_MB:-4096}"
CPUS="${CPUS:-2}"
DISK_SIZE="${DISK_SIZE:-40G}"          # used when --disk file doesn't exist yet
HTTP_PORT="${HTTP_PORT:-6080}"         # public noVNC HTTPS port
VNC_DISPLAY="${VNC_DISPLAY:-0}"        # VNC :0 = TCP 5900, localhost only
VNC_PASSWORD="${VNC_PASSWORD:-}"       # auto-generated if empty

ISO=""
DISK=""
usage() {
    grep '^#' "$0" | head -16 | sed 's/^# \?//'
    exit 1
}
while [[ $# -gt 0 ]]; do
    case "$1" in
        --iso)  ISO="$2";  shift 2 ;;
        --disk) DISK="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
done
[[ -n "$ISO" || -n "$DISK" ]] || usage
[[ -z "$ISO" || -f "$ISO" ]] || { echo "ISO not found: $ISO" >&2; exit 1; }

for cmd in qemu-system-x86_64 qemu-img websockify openssl python3; do
    command -v "$cmd" >/dev/null || { echo "missing dependency: $cmd (run cloud/provision-server.sh)" >&2; exit 1; }
done

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

# --- Persistent disk --------------------------------------------------------
if [[ -n "$DISK" && ! -f "$DISK" ]]; then
    echo "[cloud] Creating persistent disk $DISK ($DISK_SIZE) ..."
    qemu-img create -f qcow2 "$DISK" "$DISK_SIZE"
fi

# --- VNC password (QEMU auth, second factor behind TLS) ---------------------
if [[ -z "$VNC_PASSWORD" ]]; then
    if [[ -f "$STATE_DIR/vnc-password" ]]; then
        VNC_PASSWORD="$(cat "$STATE_DIR/vnc-password")"
    else
        VNC_PASSWORD="$(openssl rand -base64 12 | tr -dc 'a-zA-Z0-9' | head -c 8)"
        (umask 077; printf '%s' "$VNC_PASSWORD" > "$STATE_DIR/vnc-password")
    fi
fi

# --- TLS certificate for the browser connection -----------------------------
CERT="$STATE_DIR/novnc-cert.pem"
KEY="$STATE_DIR/novnc-key.pem"
if [[ ! -f "$CERT" ]]; then
    echo "[cloud] Generating self-signed TLS certificate ..."
    openssl req -x509 -nodes -newkey rsa:3072 -days 825 \
        -subj "/CN=secureos-cloud" \
        -keyout "$KEY" -out "$CERT" 2>/dev/null
    chmod 600 "$KEY"
fi

# --- QEMU -------------------------------------------------------------------
ACCEL_ARGS=(-accel tcg)
if [[ -w /dev/kvm ]]; then
    ACCEL_ARGS=(-enable-kvm -cpu host)
    echo "[cloud] KVM acceleration enabled."
else
    echo "[cloud] WARNING: /dev/kvm not available — falling back to slow TCG emulation."
fi

QMP_SOCK="$STATE_DIR/qmp.sock"
QEMU_ARGS=(
    "${ACCEL_ARGS[@]}"
    -m "$RAM_MB" -smp "$CPUS"
    -vga virtio
    -device "virtio-net-pci,netdev=net0"
    -netdev "user,id=net0"
    -audiodev "none,id=snd0"
    -vnc "127.0.0.1:${VNC_DISPLAY},password=on"
    -qmp "unix:${QMP_SOCK},server,nowait"
    -name "SecureOS,process=secureos-vm"
    -daemonize
    -pidfile "$STATE_DIR/qemu.pid"
)
[[ -n "$DISK" ]] && QEMU_ARGS+=(-drive "file=$DISK,format=qcow2,if=virtio")
[[ -n "$ISO"  ]] && QEMU_ARGS+=(-cdrom "$ISO" -boot "${DISK:+once=}d")

echo "[cloud] Starting SecureOS VM (${RAM_MB}MB RAM, ${CPUS} vCPU) ..."
qemu-system-x86_64 "${QEMU_ARGS[@]}"

# Set the VNC password over QMP (never on the command line / process list)
python3 - "$QMP_SOCK" "$VNC_PASSWORD" <<'PYEOF'
import json, socket, sys, time
sock_path, password = sys.argv[1], sys.argv[2]
for _ in range(50):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.connect(sock_path)
        break
    except OSError:
        time.sleep(0.2)
else:
    sys.exit("QMP socket never appeared")
f = s.makefile("rw")
json.loads(f.readline())                       # greeting
def cmd(obj):
    f.write(json.dumps(obj) + "\n"); f.flush()
    return json.loads(f.readline())
cmd({"execute": "qmp_capabilities"})
r = cmd({"execute": "change-vnc-password", "arguments": {"password": password}})
if "error" in r:
    sys.exit(f"failed to set VNC password: {r}")
PYEOF
echo "[cloud] VNC password set."

# --- noVNC / websockify (public HTTPS endpoint) -----------------------------
VNC_PORT=$((5900 + VNC_DISPLAY))
NOVNC_WEB=/usr/share/novnc
[[ -d "$NOVNC_WEB" ]] || NOVNC_WEB="$(dirname "$(command -v websockify)")/../share/novnc"

echo "[cloud] Starting noVNC on https://0.0.0.0:${HTTP_PORT}/vnc.html ..."
websockify --daemon \
    --web "$NOVNC_WEB" \
    --cert "$CERT" --key "$KEY" \
    "$HTTP_PORT" "127.0.0.1:$VNC_PORT"

cat <<EOF

===============================================================
 SecureOS is running in the cloud.

   URL:           https://$(hostname -I 2>/dev/null | awk '{print $1}'):${HTTP_PORT}/vnc.html
   VNC password:  ${VNC_PASSWORD}
   (stored in $STATE_DIR/vnc-password)

 The certificate is self-signed — your browser will warn once.
 Stop with:  sudo $SCRIPT_DIR/stop-cloud.sh
===============================================================
EOF
