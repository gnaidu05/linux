#!/usr/bin/env bash
# CloudPC session startup (runs as the unprivileged desktop user).
# Starts Xvnc bound to localhost, XFCE on top of it, and noVNC/websockify
# on 6901 for the reverse proxy.
set -euo pipefail

GEOM="${DISPLAY_GEOMETRY:-1600x900}"
DISPLAY_NUM=1
NOVNC_PORT=6901
VNC_PORT=$((5900 + DISPLAY_NUM))

export HOME="${HOME_DIR:-$HOME}"
cd "$HOME"

mkdir -p "$HOME/.vnc" "$HOME/.config"
# First run of a fresh volume: seed XDG dirs
command -v xdg-user-dirs-update >/dev/null && xdg-user-dirs-update || true

# Xvnc: no VNC-level auth (SecurityTypes None) but bound to localhost —
# the ONLY way in is websockify on 6901, which is only reachable from the
# reverse proxy network, which requires a web login. Defense in depth is
# at the network + auth layer, not a shared static VNC password.
rm -f /tmp/.X${DISPLAY_NUM}-lock /tmp/.X11-unix/X${DISPLAY_NUM} 2>/dev/null || true

Xvnc ":${DISPLAY_NUM}" \
    -geometry "$GEOM" -depth 24 \
    -localhost yes \
    -SecurityTypes None \
    -desktop "CloudPC (${DESKTOP_USER:-user})" \
    &
XVNC_PID=$!

export DISPLAY=":${DISPLAY_NUM}"
for _ in $(seq 50); do
    [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ] && break
    sleep 0.2
done

# Desktop session
dbus-launch --exit-with-session startxfce4 &

# noVNC + websocket bridge, listening on all container interfaces (the
# container itself is only attached to an internal network with the proxy).
websockify --web /usr/share/novnc "0.0.0.0:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" &
WS_PID=$!

term() { kill "$WS_PID" "$XVNC_PID" 2>/dev/null || true; exit 0; }
trap term TERM INT

# Keep PID 1 alive while Xvnc lives
wait "$XVNC_PID"
