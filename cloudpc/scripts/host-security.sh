#!/usr/bin/env bash
#
# Host-level security for a CloudPC VPS: UFW default-deny firewall and
# fail2ban watching the CloudPC auth log. Run as root on the host.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUDPC_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ufw fail2ban

echo "[host] Firewall: default deny incoming; allow SSH + HTTPS only..."
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 443/tcp comment 'CloudPC HTTPS'
ufw --force enable
ufw status verbose

echo "[host] fail2ban: jail for the CloudPC login endpoint..."
install -m 644 "$CLOUDPC_DIR/fail2ban/filter.d/cloudpc-auth.conf" \
    /etc/fail2ban/filter.d/cloudpc-auth.conf
sed "s|__AUTH_LOG__|$CLOUDPC_DIR/data/log/cloudpc/auth.log|" \
    "$CLOUDPC_DIR/fail2ban/jail.d/cloudpc.conf" \
    > /etc/fail2ban/jail.d/cloudpc.conf
systemctl enable fail2ban
systemctl restart fail2ban
sleep 2
fail2ban-client status cloudpc-auth || true

echo "[host] Done. Note: Docker's published port 443 bypasses UFW's INPUT
chain by design (DOCKER-USER chain); the compose stack only publishes 443,
so exposure is identical. SSH and everything else on the host itself is
governed by the UFW rules above."
