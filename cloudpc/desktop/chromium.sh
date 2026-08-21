#!/bin/sh
# Chromium launcher for containerized sessions.
# Prefers a vendored (offline) build at /opt/chromium/chrome; otherwise uses
# the apt-installed chromium. --no-sandbox: Chromium's setuid/userns sandbox
# cannot start inside an unprivileged container with all capabilities
# dropped; process isolation is provided by the container boundary itself.
# This matches how Kasm/Webtop images ship browsers.
if [ -x /opt/chromium/chrome ]; then
    BROWSER=/opt/chromium/chrome
elif command -v chromium >/dev/null 2>&1 && [ "$(command -v chromium)" != /usr/local/bin/chromium ]; then
    BROWSER="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
    BROWSER=chromium-browser
else
    echo "No Chromium binary found (neither vendored nor apt)." >&2
    exit 1
fi

exec "$BROWSER" \
    --no-sandbox \
    --disable-dev-shm-usage \
    --no-first-run \
    --password-store=basic \
    "$@"
