#!/usr/bin/env bash
# Populate desktop/vendor/chromium with a full Chromium build.
#
# Preference order:
#   1. An existing local Playwright Chromium (PLAYWRIGHT_BROWSERS_PATH or
#      ~/.cache/ms-playwright) — copied, no network needed.
#   2. Download via 'npx playwright-core install chromium'.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$SCRIPT_DIR/../desktop/vendor/chromium"

find_local() {
    local roots=()
    [[ -n "${PLAYWRIGHT_BROWSERS_PATH:-}" ]] && roots+=("$PLAYWRIGHT_BROWSERS_PATH")
    roots+=("$HOME/.cache/ms-playwright" /opt/pw-browsers)
    for root in "${roots[@]}"; do
        for d in "$root"/chromium-*/chrome-linux "$root"/chromium-*; do
            if [[ -x "$d/chrome" ]]; then
                echo "$d"
                return 0
            fi
        done
    done
    return 1
}

SRC="$(find_local || true)"
if [[ -z "$SRC" ]]; then
    echo "[chromium] No local build found; downloading via playwright-core..."
    command -v npx >/dev/null || { echo "npx (nodejs) required" >&2; exit 1; }
    export PLAYWRIGHT_BROWSERS_PATH="$SCRIPT_DIR/../.pw-cache"
    npx --yes playwright-core install chromium
    SRC="$(find_local)" || { echo "download failed" >&2; exit 1; }
fi

echo "[chromium] Copying from $SRC ..."
rm -rf "$DEST"
mkdir -p "$DEST"
cp -a "$SRC/." "$DEST/"
chmod 755 "$DEST/chrome"
echo "[chromium] $("$DEST/chrome" --version 2>/dev/null || echo 'copied') -> desktop/vendor/chromium"
