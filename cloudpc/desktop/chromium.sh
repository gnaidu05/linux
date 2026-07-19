#!/bin/sh
# Chromium launcher for containerized sessions.
# --no-sandbox: Chromium's setuid/userns sandbox cannot start inside an
# unprivileged container with all capabilities dropped; process isolation
# is provided by the container boundary itself. This matches how
# Kasm/Webtop images ship browsers.
exec /opt/chromium/chrome \
    --no-sandbox \
    --disable-dev-shm-usage \
    --no-first-run \
    --password-store=basic \
    "$@"
