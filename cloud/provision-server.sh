#!/usr/bin/env bash
#
# Provision a fresh cloud server (Debian 12 / Ubuntu 22.04+) to host
# SecureOS with browser access. Run once as root on the server:
#
#   sudo ./cloud/provision-server.sh
#
# Then start the OS with cloud/run-cloud.sh, or enable the systemd service:
#
#   sudo cp cloud/secureos-cloud.service /etc/systemd/system/
#   sudo systemctl enable --now secureos-cloud
#
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

HTTP_PORT="${HTTP_PORT:-6080}"

echo "[provision] Installing QEMU/KVM, noVNC, websockify ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y qemu-system-x86 qemu-utils novnc websockify openssl python3 ufw

if [[ -e /dev/kvm ]]; then
    echo "[provision] KVM available — hardware acceleration will be used."
else
    echo "[provision] WARNING: /dev/kvm missing. Choose a cloud instance with"
    echo "            nested virtualization (most bare-metal or *.metal types,"
    echo "            GCP with nested virt enabled, Hetzner/OVH/DO standard VMs)."
fi

echo "[provision] Configuring firewall (allow SSH + noVNC only) ..."
ufw allow OpenSSH
ufw allow "$HTTP_PORT"/tcp comment 'SecureOS noVNC'
ufw --force enable

echo
echo "[provision] Done. Next steps:"
echo "  1. Copy your built ISO here (scp out/secureos-1.0-amd64.iso ...)"
echo "     or build it on this server with: sudo ./build.sh"
echo "  2. First boot + install to a persistent virtual disk:"
echo "       sudo ./cloud/run-cloud.sh --iso out/secureos-1.0-amd64.iso --disk secureos.qcow2"
echo "     In the browser session run: sudo secureos-install /dev/vda"
echo "  3. After install, boot straight from the disk:"
echo "       sudo ./cloud/run-cloud.sh --disk secureos.qcow2"
echo "  4. Open https://<server-ip>:${HTTP_PORT}/vnc.html"
