#!/usr/bin/env bash
# Enable and configure the security stack: firewall, MAC, IDS, updates.
# Static config files were already overlaid from files/ by build.sh;
# this script enables services and applies settings that need commands.
# Runs INSIDE the chroot.
set -euo pipefail

CONF_DIR=/tmp/secureos/config
source "$CONF_DIR/build.conf"

# --- Firewall: default deny incoming --------------------------------------
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw logging low
# No inbound services are exposed by default. SSH is installed but disabled;
# if enabled later, admins should run: ufw limit ssh
sed -i 's/^ENABLED=no/ENABLED=yes/' /etc/ufw/ufw.conf
systemctl enable ufw

# --- Mandatory Access Control: AppArmor ------------------------------------
systemctl enable apparmor
# Kernel cmdline flags for AppArmor + lockdown are added by the installer
# (grub config on installed systems); live boot uses Debian defaults.

# --- Audit framework -------------------------------------------------------
systemctl enable auditd
# Rules shipped in /etc/audit/rules.d/99-secureos.rules (from files/)

# --- Brute-force protection ------------------------------------------------
systemctl enable fail2ban

# --- Automatic security updates -------------------------------------------
systemctl enable unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# --- Entropy daemon --------------------------------------------------------
systemctl enable haveged

# --- Antivirus -------------------------------------------------------------
if [[ "$ENABLE_CLAMAV" == "yes" ]]; then
    systemctl enable clamav-freshclam
    # clamav-daemon left disabled by default (heavy); on-demand scans work.
fi

# --- SSH: installed but OFF by default (opt-in service) --------------------
systemctl disable ssh 2>/dev/null || systemctl disable sshd 2>/dev/null || true
# Hardened settings live in /etc/ssh/sshd_config.d/99-secureos.conf

# --- Filesystem hygiene ----------------------------------------------------
# Secure permissions on sensitive files
chmod 600 /etc/shadow /etc/gshadow 2>/dev/null || true
chmod 644 /etc/passwd /etc/group
chmod 700 /root

# Restrict cron/at to root and admins
printf 'root\n' > /etc/cron.allow
printf 'root\n' > /etc/at.allow
chmod 600 /etc/cron.allow /etc/at.allow

# Remove unnecessary setuid bits from binaries that don't need them
for bin in /usr/bin/wall /usr/bin/write.ul /usr/bin/write; do
    [[ -e "$bin" ]] && chmod u-s,g-s "$bin" || true
done

# --- Login banners ---------------------------------------------------------
cat > /etc/issue <<'EOF'
SecureOS — Authorized use only.
All activity may be monitored and reported.
EOF
cp /etc/issue /etc/issue.net

# --- File integrity (optional) ---------------------------------------------
if [[ "$ENABLE_AIDE" == "yes" ]]; then
    aideinit -y -f || true
fi
