#!/usr/bin/env bash
#
# CloudPC verification harness. Run after setup.sh on the deployment host:
#
#   ./scripts/verify.sh <admin-password> <user-password>
#
# (passwords = the CURRENT portal passwords for the two accounts)
# Exercises the deployed stack end to end and prints PASS/FAIL per check.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1

BASE="${BASE:-https://127.0.0.1:443}"
APW="${1:?admin password}"; UPW="${2:?user password}"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf 'PASS  %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$*"; }
check(){ local d="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi; }

CURL="curl -sk --max-time 15"
J1=$(mktemp); J2=$(mktemp); trap 'rm -f "$J1" "$J2"' EXIT

# 1. Login page over HTTPS
$CURL "$BASE/login" | grep -q "Sign in" && ok "login page served over HTTPS" \
                                        || bad "login page served over HTTPS"

# 2. TLS is actually on (plain HTTP on 443 must fail)
curl -s --max-time 10 "http://127.0.0.1:443/login" 2>/dev/null | grep -q "Sign in" \
    && bad "plain HTTP rejected on 443" || ok "plain HTTP rejected on 443"

# 3. Wrong credentials rejected (401)
code=$($CURL -o /dev/null -w '%{http_code}' -d "username=admin&password=WRONG-guess-1!" "$BASE/login")
[ "$code" = "401" ] && ok "wrong password -> 401" || bad "wrong password -> 401 (got $code)"

# 4. Unauthenticated desktop access -> redirect to login
code=$($CURL -o /dev/null -w '%{http_code}' "$BASE/desktop/admin/")
[ "$code" = "302" ] && ok "unauthenticated desktop -> 302 login" \
                    || bad "unauthenticated desktop -> 302 login (got $code)"

# 5. Forced password change on first login (throwaway probe user).
#    A fresh account must be sent to /change-password and blocked from its
#    desktop until the password is changed.
PROBE="probe_$$"
docker compose exec -T auth python3 /app/manage.py add "$PROBE" --role user \
    --password 'ProbeInit!2026x' >/dev/null 2>&1
JP=$(mktemp)
redir=$($CURL -c "$JP" -o /dev/null -w '%{redirect_url}' \
        -d "username=$PROBE&password=ProbeInit!2026x" "$BASE/login")
case "$redir" in
  *change-password*) ok "first login forces password change (redirect to /change-password)";;
  *) bad "first login forces password change (got redirect: $redir)";;
esac
# via the public path: desktop blocked (302 to login) while must_change set
code=$($CURL -b "$JP" -o /dev/null -w '%{http_code}' "$BASE/desktop/$PROBE/vnc.html")
[ "$code" = "302" ] && ok "desktop blocked until password changed (302)" \
                    || bad "desktop blocked until password changed (got $code)"
docker compose exec -T auth python3 /app/manage.py del "$PROBE" >/dev/null 2>&1
rm -f "$JP"

# Activate the two real accounts through the first-login change flow, then
# use the rotated passwords for the steady-state tests below. This also
# exercises the password-quality policy (a weak new password is rejected).
# Rotated passwords must NOT contain the username (policy rejects that),
# so avoid the substrings "admin"/"user".
NADMIN="Rotated-9x!Kbtqwm"; NUSER="Shifted-7z!Pmvnrt"
activate() { # jar user current_pw new_pw
    local jar="$1" u="$2" cur="$3" new="$4" redir
    redir=$($CURL -c "$jar" -o /dev/null -w '%{redirect_url}' \
            -d "username=$u&password=$cur" "$BASE/login")
    if printf '%s' "$redir" | grep -q change-password; then
        # reject weak password first (evidence of policy), then set strong one
        weak=$($CURL -b "$jar" -o /dev/null -w '%{http_code}' \
               -d "current=$cur&new=weak&confirm=weak" "$BASE/change-password")
        [ "$weak" = "400" ] && ok "$u: weak new password rejected (400)" \
                            || bad "$u: weak new password rejected (got $weak)"
        $CURL -b "$jar" -c "$jar" -o /dev/null \
              -d "current=$cur&new=$new&confirm=$new" "$BASE/change-password"
    fi
}
# 6. Both users can log in and reach only their own desktop (post-activation)
reach() { # jar user pw -> http code of own desktop
    $CURL -c "$1" -b "$1" -o /dev/null -d "username=$2&password=$3" "$BASE/login"
    $CURL -b "$1" -o /dev/null -w '%{http_code}' "$BASE/desktop/$2/vnc.html"
}
activate "$J1" admin "$APW" "$NADMIN"
activate "$J2" user  "$UPW" "$NUSER"
[ "$(reach "$J1" admin "$NADMIN")" = "200" ] && ok "admin reaches own desktop (vnc.html 200)" \
                                             || bad "admin reaches own desktop"
[ "$(reach "$J2" user  "$NUSER")" = "200" ] && ok "user reaches own desktop (vnc.html 200)" \
                                            || bad "user reaches own desktop"

# 7. Cross-user access denied (user session cannot reach admin desktop)
code=$($CURL -b "$J2" -o /dev/null -w '%{http_code}' "$BASE/desktop/admin/vnc.html")
[ "$code" = "403" ] && ok "user blocked from admin desktop (403)" \
                    || bad "user blocked from admin desktop (got $code)"

# 8. Rate limiting on /login
codes=$(for i in $(seq 12); do $CURL -o /dev/null -w '%{http_code}\n' \
        -d "username=nobody&password=x$i" "$BASE/login"; done)
echo "$codes" | grep -q 429 && ok "rate limit triggers 429 on login flood" \
                            || bad "rate limit triggers 429 on login flood"

# 9. Session apps present and launchable
for c in cloudpc-desktop-admin-1 cloudpc-desktop-user-1; do
    docker exec "$c" bash -c 'command -v chromium && command -v libreoffice \
        && command -v vlc && command -v gimp && command -v thunar \
        && command -v mousepad && command -v xarchiver && command -v ristretto \
        && command -v xfce4-terminal' >/dev/null 2>&1 \
        && ok "$c: all applications installed" || bad "$c: all applications installed"
    docker exec "$c" pgrep -x Xvnc >/dev/null && ok "$c: Xvnc running" || bad "$c: Xvnc running"
    docker exec "$c" pgrep -f xfce4-session >/dev/null && ok "$c: XFCE session running" \
                                                       || bad "$c: XFCE session running"
done

# 10. Session isolation at the network layer
docker exec cloudpc-desktop-user-1 getent hosts desktop-admin >/dev/null 2>&1 \
    && bad "desktops cannot resolve each other" || ok "desktops cannot resolve each other"

# 11. sudo policy
echo "$(cat secrets/admin_unix_password)" | docker exec -i cloudpc-desktop-admin-1 \
    sudo -S -k id 2>/dev/null | grep -q uid=0 \
    && ok "admin sudo works (password required)" || bad "admin sudo works"
docker exec cloudpc-desktop-user-1 sudo -n id >/dev/null 2>&1 \
    && bad "standard user has no sudo" || ok "standard user has no sudo"
# inspect as root (dockerd is root) — the desktop user cannot read shadow
docker exec -u root cloudpc-desktop-admin-1 passwd -S root 2>/dev/null | grep -qE ' L ' \
    && ok "root locked in desktop" || bad "root locked in desktop"

# 12. Container hardening flags
insp() { docker inspect -f "$2" "$1" 2>/dev/null; }
[ "$(insp cloudpc-proxy-1 '{{.HostConfig.ReadonlyRootfs}}')" = "true" ] \
    && ok "proxy is read-only" || bad "proxy is read-only"
[ "$(insp cloudpc-auth-1 '{{.HostConfig.ReadonlyRootfs}}')" = "true" ] \
    && ok "auth is read-only" || bad "auth is read-only"
insp cloudpc-desktop-user-1 '{{.HostConfig.SecurityOpt}}' | grep -q no-new-privileges \
    && ok "user desktop: no-new-privileges" || bad "user desktop: no-new-privileges"
[ "$(insp cloudpc-desktop-user-1 '{{.HostConfig.CapDrop}}')" = "[ALL]" ] \
    && ok "user desktop: cap_drop ALL" || bad "user desktop: cap_drop ALL"
[ "$(insp cloudpc-desktop-admin-1 '{{.HostConfig.Privileged}}')" = "false" ] \
    && ok "no privileged containers" || bad "no privileged containers"
[ "$(insp cloudpc-desktop-user-1 '{{.HostConfig.Memory}}')" != "0" ] \
    && ok "memory limits set" || bad "memory limits set"

# 13. Persistence across restart
docker exec cloudpc-desktop-user-1 bash -c 'echo persist-test > ~/persist-check.txt'
docker compose restart desktop-user >/dev/null 2>&1
sleep 8
docker exec cloudpc-desktop-user-1 cat /home/user/persist-check.txt 2>/dev/null \
    | grep -q persist-test && ok "home persists across container restart" \
                           || bad "home persists across container restart"

echo
echo "== $PASS passed, $FAIL failed =="
exit $((FAIL > 0))
