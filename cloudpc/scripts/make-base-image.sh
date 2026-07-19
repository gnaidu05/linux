#!/usr/bin/env bash
# Build the cloudpc/base:24.04 image locally with debootstrap.
# No container registry access is needed anywhere in this project.
set -euo pipefail

command -v debootstrap >/dev/null || {
    echo "[base] Installing debootstrap..."
    apt-get update -qq && apt-get install -y -qq debootstrap
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "[base] debootstrap Ubuntu noble (minbase)..."
debootstrap --arch=amd64 --variant=minbase noble "$WORK/rootfs" \
    http://archive.ubuntu.com/ubuntu

# Full component set for the desktop packages
cat > "$WORK/rootfs/etc/apt/sources.list" <<'EOF'
deb http://archive.ubuntu.com/ubuntu noble main universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-updates main universe multiverse
deb http://security.ubuntu.com/ubuntu noble-security main universe multiverse
EOF

echo "[base] Importing into Docker as cloudpc/base:24.04..."
tar -C "$WORK/rootfs" -c . | docker import \
    --change 'CMD ["/bin/bash"]' \
    --change 'ENV LANG=C.UTF-8' \
    - cloudpc/base:24.04

echo "[base] Done."
