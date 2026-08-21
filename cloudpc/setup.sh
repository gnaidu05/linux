#!/usr/bin/env bash
#
# CloudPC one-command deployment.
#
#   sudo ./setup.sh                # build + start + firewall/fail2ban
#
# Run as root on a fresh Ubuntu VPS. Host hardening (UFW default-deny +
# fail2ban) runs by default; opt out with SKIP_HOST=1. Browsers install
# from apt (no Node.js); set OFFLINE_CHROMIUM=1 to vendor Chromium instead.
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

# --- Chromium payload (optional offline fallback) ---------------------------
# The desktop image installs Chromium from apt (xtradeb PPA) by default, so
# nothing is needed here for a normal networked VPS. For air-gapped or
# PPA-restricted builds, set OFFLINE_CHROMIUM=1 to vendor a Chromium build
# into desktop/vendor/chromium (needs a local Playwright cache or npx).
if [[ "${OFFLINE_CHROMIUM:-0}" == "1" && ! -x desktop/vendor/chromium/chrome ]]; then
    log "OFFLINE_CHROMIUM=1: vendoring a Chromium build for the image..."
    ./scripts/fetch-chromium.sh || die "could not vendor Chromium (see scripts/fetch-chromium.sh)"
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

# --- Host firewall + fail2ban (default ON; the spec requires them) ----------
# Set SKIP_HOST=1 to opt out (e.g. when a firewall is managed elsewhere).
# host-security.sh allows OpenSSH before enabling UFW, so SSH stays reachable.
# Best-effort: a failure here (no systemd, unusual host) must not abort setup.
HOST_HARDENED="no"
if [[ "${SKIP_HOST:-0}" != "1" ]]; then
    if [[ $EUID -eq 0 ]]; then
        if ./scripts/host-security.sh; then
            HOST_HARDENED="yes"
        else
            log "WARNING: host hardening did not complete; run scripts/host-security.sh manually."
        fi
    else
        log "Not root: skipping firewall/fail2ban. Run: sudo ./scripts/host-security.sh"
    fi
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

 Host firewall + fail2ban: ${HOST_HARDENED}$([ "$HOST_HARDENED" = no ] && echo "  (run: sudo ./scripts/host-security.sh)")
 TLS: self-signed (replace with Let's Encrypt — see README.md)
===============================================================
EOF
