# CloudPC — a self-hostable cloud desktop in your browser

CloudPC turns one Ubuntu VPS into a **browser-accessible Linux desktop
service**: users open a URL, sign in on a web login page, and get their own
persistent XFCE desktop with browsers and office apps — delivered over HTTPS
by noVNC. No client software.

```
[browser] --443 HTTPS--> nginx ──auth_request──> auth portal (Flask, argon2)
                           │
                           ├─ /desktop/admin/ ──> desktop-admin container
                           └─ /desktop/user/  ──> desktop-user  container
                                (XFCE + TigerVNC + noVNC, one per user,
                                 isolated networks, persistent home volumes)
```

The base image is built **with no container registry access required**:
produced locally by debootstrap and `docker import`, so the stack deploys
even on networks where Docker Hub is blocked. Packages (including both
browsers) come from the normal Ubuntu archives and two `.deb` PPAs over
plain apt — no Docker registry and no Node.js toolchain are needed.

## Why XFCE

XFCE was chosen over KDE because it needs roughly a third of the RAM per
session, has no compositing effects (which render poorly and waste bandwidth
over VNC), and still provides a complete, familiar desktop. On a VPS every
concurrent session counts.

## What's inside each desktop

| Category | Application |
|----------|-------------|
| Browsers | Firefox (`ppa:mozillateam` deb); Chromium (`ppa:xtradeb` deb, with an optional vendored fallback — see note) |
| Office | LibreOffice Writer, Calc, Impress |
| Media | VLC |
| Images | Ristretto (viewer), GIMP (editor) |
| Files | Thunar file manager, Xarchiver archive manager |
| Editing | Mousepad text editor |
| Terminal | xfce4-terminal |
| Misc | Galculator, XFCE task manager |

> **Browser note:** Ubuntu ships both Firefox and Chromium only as snaps,
> which cannot run in a container, so both are installed as real `.deb`s:
> Firefox from `ppa:mozillateam/ppa` and Chromium from `ppa:xtradeb/apps`.
> Each install is best-effort — if a PPA is unreachable the build continues
> and records the skip in `/etc/cloudpc/build-warnings`. For air-gapped or
> PPA-restricted builds, set `OFFLINE_CHROMIUM=1` on `setup.sh` to vendor a
> Chromium build into the image (`scripts/fetch-chromium.sh`); the launcher
> prefers that vendored build when present.

## Quick start (fresh Ubuntu 22.04/24.04 VPS)

```bash
apt-get update && apt-get install -y docker.io docker-compose-v2 git
git clone <this-repo> && cd <repo>/cloudpc
sudo ./setup.sh
```

That single command builds the base image, the desktop/auth/proxy images
(browsers via apt — no Node.js needed), generates a self-signed TLS
certificate and secrets, starts the stack, creates the two initial accounts,
and — because it runs as root — applies the host firewall and fail2ban by
default (opt out with `SKIP_HOST=1 sudo ./setup.sh`). At the end it prints:

- the URL: `https://<server-ip>/`
- the **initial passwords** for `admin` and `user` (randomly generated,
  shown once)

### Default accounts

| Account | Role | Desktop URL | sudo |
|---------|------|-------------|------|
| `admin` | administrator | `/desktop/admin/` | yes — password in `secrets/admin_unix_password` |
| `user`  | standard | `/desktop/user/` | no (by design) |

Both accounts **must set a new password at first web login** (12+ characters
with upper/lower/digit/symbol enforced). The root account inside every
desktop container is locked.

## Adding users

```bash
./scripts/add-user.sh alice user      # or: alice admin
```

The two built-in accounts (`admin`, `user`) work out of the box with no
extra steps. `add-user.sh` covers a **third or later** user: it creates the
portal account (printing a one-time initial password) and writes the nginx
route immediately, then — because each user gets their own isolated
container, network, and home volume — prints a ready-to-paste
`docker-compose.override.yml` snippet for the new desktop service. That last
step is a deliberate manual edit (adding a container is not something to do
silently). After pasting the snippet:

```bash
docker compose up -d && docker compose exec proxy nginx -s reload
```

Other account operations (inside the auth container):

```bash
docker compose exec auth python3 /app/manage.py list
docker compose exec auth python3 /app/manage.py passwd alice   # reset + force change
docker compose exec auth python3 /app/manage.py del alice
```

## TLS in production (Let's Encrypt)

The stack starts with a self-signed certificate in `secrets/tls/`. To
replace it with a real one:

```bash
# DNS A record for desktop.example.com -> your server, then:
sudo apt-get install -y certbot
sudo systemctl stop cloudpc 2>/dev/null; docker compose stop proxy  # free 443
sudo certbot certonly --standalone -d desktop.example.com
sudo ln -sf /etc/letsencrypt/live/desktop.example.com/fullchain.pem secrets/tls/fullchain.pem
sudo ln -sf /etc/letsencrypt/live/desktop.example.com/privkey.pem  secrets/tls/privkey.pem
docker compose up -d proxy
# renewals: add a deploy hook that runs `docker compose restart proxy`
```

(Alternatively put Caddy on the host in front of the stack for fully
automatic certificates; the nginx container then listens only on localhost.)

## Security model

**Authentication (web layer — nothing is served without it)**
- Login portal with argon2id password hashes; sessions are HttpOnly,
  Secure, SameSite=Strict cookies (8 h lifetime)
- Strong password policy (≥12 chars, 4 classes, username forbidden) and
  **forced password change at first login**
- Account lockout: 5 consecutive failures → 15 min lock; per-IP throttle
  (20 failures / 15 min across accounts)
- nginx `limit_req` on `/login`: 10 requests/min/IP (burst 5) → HTTP 429
- Every desktop request passes nginx `auth_request`; the portal approves
  only if the session user owns that `/desktop/<user>/` path — users cannot
  reach each other's desktops even with a valid session
- Auth events land in `data/log/cloudpc/auth.log` for fail2ban

**Transport**
- HTTPS only; TLS 1.2/1.3, modern ciphers, HSTS; nothing listens on port 80

**Container hardening**
- No privileged containers anywhere; every service: `cap_drop: ALL`
- Standard-user desktop and auth/proxy: `no-new-privileges`; proxy and auth
  are `read_only` with tmpfs for runtime state
- Admin desktop: minimal capabilities added back (SETUID/SETGID/AUDIT_WRITE/
  CHOWN/DAC_OVERRIDE/FOWNER) because working `sudo` requires setuid — the
  standard-user container has no sudo and keeps the strictest profile
- Per-session resource limits: 3 GB RAM, 2 CPUs, 1024 pids
- Desktops run as an unprivileged user (uid 1000); root is locked;
  VNC listens on the container's localhost only with the websocket bridge
  reachable solely from the proxy's network
- Network isolation: each desktop is on its own Docker network shared only
  with the proxy; the auth portal's network is `internal` (no egress);
  desktops cannot reach each other

**Host (scripts/host-security.sh — run by default from `setup.sh` as root)**
- UFW default-deny incoming; only SSH and 443 open (OpenSSH is allowed
  before UFW is enabled, so remote access is never cut off)
- fail2ban jail on the auth log: 10 failures / 10 min → 1 h ban, applied in
  the `DOCKER-USER` chain so bans work for Docker-published ports (Docker
  bypasses the normal INPUT chain — the script handles this correctly)
- fail2ban is the durable brute-force layer: the portal's own lockout
  counters are in-memory and reset if the auth container restarts, so the
  host jail is what persists bans across restarts

**Adding-user note:** the two built-in accounts need no extra steps; a third
user requires pasting one generated compose snippet (see "Adding users").

**Known trade-offs (documented, deliberate)**
- Chromium runs with `--no-sandbox` inside the session container: its
  setuid/userns sandbox cannot start in an unprivileged, cap-dropped
  container. Isolation is provided by the container boundary (as in
  Kasm/Webtop images). Keep untrusted browsing in the standard-user
  desktop, which has the strictest container profile.
- VNC itself has no second password; it is only reachable through the
  authenticated, TLS-terminated proxy path. Add a per-user VNC password in
  `desktop/startup.sh` if you want defense in depth at that layer too.

## Operations

```bash
docker compose ps                        # status
docker compose logs -f auth              # login activity (also data/log/cloudpc/auth.log)
docker compose restart desktop-user      # restart one session
docker compose down                      # stop (home volumes persist)
docker compose down -v                   # stop AND DELETE user homes
DISPLAY_GEOMETRY=1920x1080 docker compose up -d   # resolution (env per service)
```

Home directories live in the named volumes `cloudpc_home-admin` /
`cloudpc_home-user` and survive container rebuilds and restarts.

## Repository layout

```
cloudpc/
├── docker-compose.yml       four services: proxy, auth, desktop-admin, desktop-user
├── setup.sh                 one-command deployment
├── auth/                    Flask login portal + user management CLI
├── desktop/                 XFCE + TigerVNC + noVNC session image
├── proxy/                   nginx: TLS, auth_request gate, websocket proxy
├── fail2ban/                filter + jail for the auth log
├── scripts/                 make-base-image, gen-tls, fetch-chromium,
│                            add-user, host-security
├── secrets/                 (generated; git-ignored) TLS, passwords
└── data/                    (generated; git-ignored) users.json, logs, routes
```
