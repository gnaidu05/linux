#!/usr/bin/env bash
# Install kernel, desktop, browsers, applications, and security packages.
# Runs INSIDE the chroot; inputs live under /tmp/secureos.
set -euo pipefail

CONF_DIR=/tmp/secureos/config
source "$CONF_DIR/build.conf"

export DEBIAN_FRONTEND=noninteractive

# Locale & timezone first so later packages configure cleanly
apt-get update
apt-get install -y --no-install-recommends locales tzdata
sed -i "s/^# *${LOCALE}/${LOCALE}/" /etc/locale.gen
locale-gen
update-locale LANG="$LOCALE"
ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime
dpkg-reconfigure -f noninteractive tzdata

read_list() {
    # Strip comments/blank lines from a package list
    grep -vE '^\s*(#|$)' "$1"
}

PKGS=()
mapfile -t -O "${#PKGS[@]}" PKGS < <(read_list "$CONF_DIR/packages/base.list")
mapfile -t -O "${#PKGS[@]}" PKGS < <(read_list "$CONF_DIR/packages/desktop-${DESKTOP}.list")
mapfile -t -O "${#PKGS[@]}" PKGS < <(read_list "$CONF_DIR/packages/browsers.list")
mapfile -t -O "${#PKGS[@]}" PKGS < <(read_list "$CONF_DIR/packages/apps.list")
mapfile -t -O "${#PKGS[@]}" PKGS < <(read_list "$CONF_DIR/packages/security.list")

[[ "$ENABLE_CLAMAV" == "yes" ]] && PKGS+=(clamav clamav-daemon clamav-freshclam)
[[ "$ENABLE_AIDE"   == "yes" ]] && PKGS+=(aide aide-common)

echo "Installing ${#PKGS[@]} packages ..."
apt-get install -y "${PKGS[@]}"

# Ship the disk installer in the live image
install -m 0755 /tmp/secureos/installer/install-to-disk.sh /usr/local/sbin/secureos-install

apt-get clean
