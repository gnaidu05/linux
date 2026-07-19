#!/usr/bin/env bash
# Create user accounts and configure authentication policy.
# Runs INSIDE the chroot.
set -euo pipefail

CONF_DIR=/tmp/secureos/config
USERS_FILE="$CONF_DIR/users.conf"

# Pull DEFAULT_PASSWORD out of users.conf (shell-style assignment line)
DEFAULT_PASSWORD="$(grep -E '^DEFAULT_PASSWORD=' "$USERS_FILE" | cut -d'"' -f2)"
[[ -n "$DEFAULT_PASSWORD" ]] || { echo "DEFAULT_PASSWORD missing from users.conf" >&2; exit 1; }

# --- Password aging & umask policy (applies to accounts created below) -----
sed -i \
    -e 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS\t365/' \
    -e 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS\t1/' \
    -e 's/^PASS_WARN_AGE.*/PASS_WARN_AGE\t14/' \
    -e 's/^UMASK.*/UMASK\t\t027/' \
    /etc/login.defs

# Encrypt with strong hash and many rounds
grep -q '^SHA_CRYPT_MIN_ROUNDS' /etc/login.defs || \
    printf 'SHA_CRYPT_MIN_ROUNDS 100000\nSHA_CRYPT_MAX_ROUNDS 200000\n' >> /etc/login.defs

# --- PAM: account lockout after repeated failures (pam_faillock) -----------
# /etc/security/faillock.conf is shipped via files/; wire faillock into PAM.
if ! grep -q pam_faillock /etc/pam.d/common-auth; then
    sed -i '/pam_unix\.so/i auth    required                        pam_faillock.so preauth' /etc/pam.d/common-auth
    sed -i '/pam_unix\.so/a auth    [default=die]                   pam_faillock.so authfail' /etc/pam.d/common-auth
    sed -i '/pam_faillock\.so authfail/a auth    sufficient                      pam_faillock.so authsucc' /etc/pam.d/common-auth
    grep -q pam_faillock /etc/pam.d/common-account || \
        printf 'account required                        pam_faillock.so\n' >> /etc/pam.d/common-account
fi

# pam_pwquality is enabled automatically by libpam-pwquality via
# /etc/pam.d/common-password; policy values live in /etc/security/pwquality.conf.

# --- Create accounts -------------------------------------------------------
while IFS=: read -r username role fullname; do
    # Skip comments, blanks, and the DEFAULT_PASSWORD line
    [[ "$username" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "$username" == DEFAULT_PASSWORD=* ]] && continue

    echo "Creating user: $username ($role)"
    useradd -m -s /bin/bash -c "$fullname" "$username"
    echo "$username:$DEFAULT_PASSWORD" | chpasswd

    case "$role" in
        admin) usermod -aG sudo,adm,cdrom,audio,video,plugdev,netdev "$username" ;;
        user)  usermod -aG cdrom,audio,video,plugdev,netdev "$username" ;;
        *)     echo "Unknown role '$role' for $username" >&2; exit 1 ;;
    esac

    # Force password change on first login
    chage -d 0 "$username"
    # Home dirs private (umask 027 handles new files; fix the dir itself)
    chmod 750 "/home/$username"
done < "$USERS_FILE"

# --- Root: locked; privileged access only via sudo -------------------------
passwd -l root

# sudo policy shipped via files/etc/sudoers.d/; validate it now
visudo -cf /etc/sudoers
for f in /etc/sudoers.d/*; do
    [[ -f "$f" ]] && visudo -cf "$f"
done

# Restrict su to sudo group members
if ! grep -qE '^auth\s+required\s+pam_wheel\.so' /etc/pam.d/su; then
    sed -i '/pam_rootok/a auth       required   pam_wheel.so group=sudo' /etc/pam.d/su
fi
