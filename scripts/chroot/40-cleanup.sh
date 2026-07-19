#!/usr/bin/env bash
# Final cleanup: shrink the image and remove build residue.
# Runs INSIDE the chroot.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get autoremove -y --purge
apt-get clean

# Build residue and caches
rm -rf /var/lib/apt/lists/*
rm -rf /var/cache/apt/archives/*.deb
rm -rf /tmp/* /var/tmp/* 2>/dev/null || true
rm -f /var/log/*.log /var/log/apt/* 2>/dev/null || true

# Machine identity must be unique per install — blank it so systemd
# regenerates it on first boot
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id

# No leftover SSH host keys in the image; regenerated on first boot by
# the shipped systemd unit (files/etc/systemd/system/regenerate-ssh-host-keys.service)
rm -f /etc/ssh/ssh_host_*
systemctl enable regenerate-ssh-host-keys.service

# Update initramfs so live-boot hooks are included
update-initramfs -u -k all
