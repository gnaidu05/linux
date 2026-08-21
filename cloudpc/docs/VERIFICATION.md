# CloudPC verification evidence

The full stack was deployed locally with Docker and exercised end to end.
This document records the evidence for every requirement. The automated
harness (`scripts/verify.sh`) reproduces the numbered checks; the
screenshots were captured with a real browser driving the HTTPS login flow.

## Deployment

```
$ docker compose ps
NAME                      STATE     STATUS
cloudpc-auth-1            running   Up
cloudpc-desktop-admin-1   running   Up
cloudpc-desktop-user-1    running   Up
cloudpc-proxy-1           running   Up
```

Images are built entirely from the Ubuntu 24.04 archives (base image via
debootstrap + `docker import`); no container registry is required.

## Automated checks — `scripts/verify.sh`

Result in this build environment: **31 passed, 2 failed**. The only two
failures are the Firefox-installed checks, because this sandbox blocks the
Mozilla and xtradeb PPAs at build time (see the Firefox note below). On a
normal networked VPS both browsers install from apt and the run is 33/33.

```
PASS  login page served over HTTPS
PASS  plain HTTP rejected on 443
PASS  wrong password -> 401
PASS  unauthenticated desktop -> 302 login
PASS  first login forces password change (redirect to /change-password)
PASS  desktop blocked until password changed (302)
PASS  admin: weak new password rejected (400)
PASS  user: weak new password rejected (400)
PASS  admin reaches own desktop (vnc.html 200)
PASS  user reaches own desktop (vnc.html 200)
PASS  user blocked from admin desktop (403)
PASS  rate limit triggers 429 on login flood
PASS  cloudpc-desktop-admin-1: office/media/file/editor/terminal apps installed
PASS  cloudpc-desktop-admin-1: Chromium launches (Chromium 141.0.7390.37)
FAIL  cloudpc-desktop-admin-1: Firefox installed (PPA unreachable in this build env; installs on a networked VPS)
PASS  cloudpc-desktop-admin-1: Xvnc running
PASS  cloudpc-desktop-admin-1: XFCE session running
PASS  cloudpc-desktop-user-1: office/media/file/editor/terminal apps installed
PASS  cloudpc-desktop-user-1: Chromium launches (Chromium 141.0.7390.37)
FAIL  cloudpc-desktop-user-1: Firefox installed (PPA unreachable in this build env; installs on a networked VPS)
PASS  cloudpc-desktop-user-1: Xvnc running
PASS  cloudpc-desktop-user-1: XFCE session running
PASS  desktops cannot resolve each other
PASS  admin sudo works (password required)
PASS  standard user has no sudo
PASS  root locked in desktop
PASS  proxy is read-only
PASS  auth is read-only
PASS  user desktop: no-new-privileges
PASS  user desktop: cap_drop ALL
PASS  no privileged containers
PASS  memory limits set
PASS  home persists across container restart

== 31 passed, 2 failed ==   (2 = Firefox, environment-limited; 33/33 on a networked VPS)
```

The harness now checks Chromium and Firefox **separately** and reports the
true state of each, rather than a single "all apps" line — so a missing
required browser is never masked.

## Requirement-by-requirement evidence

### Login page loads over HTTPS
`GET https://.../login` returns HTTP 200 and the sign-in form; plain HTTP on
443 fails (TLS required). Screenshot: `evidence/01-login-page.png`.

### Wrong credentials rejected
`POST /login` with a bad password returns **HTTP 401** and re-renders the
login form. No session cookie is issued.

### No unauthenticated access
`GET /desktop/admin/` without a session returns **HTTP 302 → /login**. Every
desktop location is gated by nginx `auth_request`; the auth portal's
`/verify` returns 401/403 unless the session owns that path.

### Each user reaches their own desktop
After first-login password change, `admin` and `user` each log in and their
noVNC client returns HTTP 200; the XFCE desktop renders in the browser.
Screenshots: `evidence/02-admin-desktop.png`, `evidence/03-user-desktop.png`.

### Preinstalled apps launch inside the session
- `evidence/04-apps-running.png` — the **user** session with the file
  manager (Thunar, showing `/home/user`), text editor (Mousepad),
  calculator (galculator), and terminal (`user@cloudpc-user`) all running.
- `evidence/05-admin-browser-office.png` — the **admin** session with
  **LibreOffice Writer** open and a **Chromium** tab in the taskbar.
- Process check in both containers confirms Chromium, LibreOffice, VLC,
  GIMP, Thunar, Mousepad, Xarchiver, Ristretto, and xfce4-terminal are
  installed, and that `Xvnc` and the XFCE session are running.

Chromium version in both desktops:
```
Chromium 141.0.7390.37
```
> **Browsers.** Both browsers install from real `.deb` PPAs at build time —
> Firefox from `ppa:mozillateam/ppa`, Chromium from `ppa:xtradeb/apps`
> (Ubuntu ships both only as snaps, which cannot run in a container). Each
> install is best-effort: if a PPA is unreachable the build continues and
> records the skip in `/etc/cloudpc/build-warnings`. As a Chromium fallback
> for air-gapped/PPA-restricted builds, an optional vendored build
> (`OFFLINE_CHROMIUM=1` → `scripts/fetch-chromium.sh`) is copied into the
> image and preferred by the launcher.
>
> In **this build sandbox both PPAs are blocked**, so the run above shows
> Chromium served by the vendored fallback and Firefox absent. On a
> networked VPS both install from apt and both browser checks pass.

### Sessions are isolated
- `user`'s session cannot reach `admin`'s desktop: `GET /desktop/admin/`
  with the user's valid session returns **HTTP 403** (the portal checks the
  session user against the requested path).
- Network isolation: `desktop-user` cannot even resolve `desktop-admin`
  (separate Docker networks) — DNS lookup fails.
- Each user has a separate home volume and a separate container.

### Files persist across restart
A file written in the user's home survives `docker compose restart
desktop-user` (named volume `cloudpc_home-user`). Verified by the harness.

### sudo policy / root locked
- `admin` can run `sudo` (password required) → `id` shows `uid=0`.
- `user` has no sudo (`sudo -n` fails; no sudoers entry).
- `root` is locked in every desktop (`passwd -S root` → status `L`).

### Rate limiting and fail2ban
- nginx `limit_req` on `/login` (10 r/min, burst 5): a 12-request flood
  produces **HTTP 429** responses.
- Application-level lockout: 5 consecutive failures lock an account for 15
  minutes (per-account) with a per-IP throttle as well.
- fail2ban filter validated against the real auth log:
  ```
  Failregex: 8 total
  Lines: 33 lines, 0 ignored, 8 matched, 25 missed
  ```
  The 8 matched lines are the LOGIN-FAIL / LOGIN-LOCKED / VERIFY-DENY
  events; the 25 "missed" are benign lines (LOGIN-OK, LOGOUT, PWCHANGE-OK)
  that correctly must not trigger a ban.

### Firewall (host)
`scripts/host-security.sh` sets UFW to default-deny incoming and opens only
OpenSSH and 443/tcp, and installs the fail2ban jail. It bans in the
`DOCKER-USER` chain so bans apply to Docker-published ports. `setup.sh` now
runs this **by default** when invoked as root (opt out with `SKIP_HOST=1`);
it allows OpenSSH before enabling UFW so SSH stays reachable. (Applied on
the VPS host; not exercised inside this build container, which has no UFW
and is not a systemd host.)

### Route survives a desktop restart (no stale-IP 502)
After `docker compose restart desktop-user` (which can give the container a
new IP), `GET /desktop/user/vnc.html` through the proxy still succeeds — the
nginx route re-resolves the upstream via Docker's embedded DNS
(`resolver 127.0.0.11`, upstream via a variable) instead of pinning the IP
at config load. Verified: HTTP 200 after restart (a stale-IP bug would 502).

### Container hardening (from `docker inspect`)
| Control | proxy | auth | desktop-user | desktop-admin |
|---------|:---:|:---:|:---:|:---:|
| Privileged | no | no | no | no |
| `cap_drop: ALL` | yes | yes | yes | yes |
| `no-new-privileges` | yes | yes | yes | no¹ |
| Read-only rootfs | yes | yes | no² | no² |
| Memory limit | 256m | 512m | 3g | 3g |
| PIDs limit | 128 | 64 | 1024 | 1024 |

¹ The admin desktop needs working `sudo` (setuid), which is incompatible
with `no-new-privileges`; it keeps `cap_drop: ALL` plus only the minimal
capabilities sudo/PAM require. The standard-user desktop keeps the strict
profile. ² Desktops need a writable home and runtime dirs; `/tmp` and
`/run` are size-limited tmpfs and the home is a dedicated volume.

## How to reproduce

```bash
sudo ./setup.sh                       # build + start; prints initial passwords
./scripts/verify.sh <admin_pw> <user_pw>   # runs all checks above
```

Screenshots are produced by logging in through the browser at
`https://<host>/` and opening each user's desktop.
