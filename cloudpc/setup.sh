#!/usr/bin/env bash
#
# CloudPC one-command deployment.
#
#   sudo ./setup.sh                # build + start the whole stack
#
# On a fresh Ubuntu VPS, run scripts/host-security.sh first (firewall +
# fail2ban), or let this script call it with SETUP_HOST=1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

log() { printf '\e[1;36m[cloudpc]\e[0m %s\n' "$*"; }
die() { printf '\e[1;31m[cloudpc]\e[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker is required (apt-get install docker.io docker-compose-v2)"
docker compose version >/dev/null 2>&1 || die "docker compose v2 is required"

mkdir -p secrets data/auth data/nginx-desktops data/log/nginx data/log/cloudpc
chmod 700 secrets

# --- TLS certificate (self-signed for testing; see README for Let's Encrypt)
if [[ ! -f secrets/tls/fullchain.pem ]]; then
    log "Generating self-signed TLS certificate (replace for production)..."
    ./scripts/gen-tls.sh
fi

# --- Admin unix password (for sudo inside the admin desktop) ----------------
if [[ ! -s secrets/admin_unix_password ]]; then
    log "Generating admin sudo password..."
    (umask 077; openssl rand -base64 18 | tr -d '/+=' | head -c 16 > secrets/admin_unix_password)
fi

# --- Chromium payload -------------------------------------------------------
# The desktop image copies a Chromium build from desktop/vendor/chromium.
# scripts/fetch-chromium.sh populates it (from a local Playwright install
# or by downloading a Playwright Chromium build).
if [[ ! -x desktop/vendor/chromium/chrome ]]; then
    log "Populating Chromium payload..."
    ./scripts/fetch-chromium.sh
fi

# --- Base image (built locally from Ubuntu archives — no registry needed) ---
if ! docker image inspect cloudpc/base:24.04 >/dev/null 2>&1; then
    log "Building Ubuntu 24.04 base image with debootstrap..."
    ./scripts/make-base-image.sh
fi

# --- Auth data ownership (auth container runs as uid 900) -------------------
chown -R 900:900 data/auth data/log/cloudpc 2>/dev/null || \
    die "run as root (needs to chown data/auth for the auth container)"

# --- Build and start --------------------------------------------------------
log "Building images (first run takes a while: LibreOffice, GIMP, VLC...)..."
docker compose build

log "Starting stack..."
docker compose up -d

# --- Seed users + desktop routes -------------------------------------------
if [[ ! -s data/auth/users.json ]]; then
    log "Creating initial users (admin, user)..."
    ./scripts/add-user.sh --seed admin admin
    ./scripts/add-user.sh --seed user user
    docker compose exec proxy nginx -s reload >/dev/null 2>&1 || \
        docker compose restart proxy >/dev/null
fi

# --- Host firewall + fail2ban (opt-in from setup) ---------------------------
if [[ "${SETUP_HOST:-0}" == "1" ]]; then
    ./scripts/host-security.sh
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

===============================================================
 CloudPC is up.

   URL:    https://${IP:-<server-ip>}/
   Users:  see the initial passwords printed above
           (each account must set a new password at first login)

 Admin sudo password (inside the admin desktop):
   secrets/admin_unix_password

 Production hardening:
   sudo ./scripts/host-security.sh    # ufw default-deny + fail2ban
   README.md                          # Let's Encrypt TLS setup
===============================================================
EOF
