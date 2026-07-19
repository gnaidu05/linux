#!/usr/bin/env bash
#
# Add a CloudPC user: portal account + nginx desktop route.
#
#   ./scripts/add-user.sh <username> <role>        role: admin | user
#   ./scripts/add-user.sh --seed <username> <role> (used by setup.sh; same,
#                                                   but skips the reload hint)
#
# For a NEW user beyond the built-in two, also add a desktop service —
# the script prints a ready-to-paste compose override snippet.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

SEED=0
if [[ "${1:-}" == "--seed" ]]; then SEED=1; shift; fi
USERNAME="${1:-}"; ROLE="${2:-}"
[[ "$USERNAME" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "usage: add-user.sh <username> <admin|user>" >&2; exit 1; }
[[ "$ROLE" == "admin" || "$ROLE" == "user" ]] || { echo "role must be admin or user" >&2; exit 1; }

# 1. Portal account (prints the initial password; must_change is set)
docker compose exec -T auth python3 /app/manage.py add "$USERNAME" --role "$ROLE"

# 2. nginx route: /desktop/<username>/ -> desktop-<username>:6901
SERVICE="desktop-$USERNAME"
sed -e "s/__USER__/$USERNAME/g" -e "s/__UPSTREAM__/$SERVICE/g" \
    proxy/desktop.locations.template > "data/nginx-desktops/$USERNAME.locations"

if [[ "$SEED" == "1" ]]; then
    exit 0
fi

# 3. New desktop container needed (the built-in admin/user services already
#    exist in docker-compose.yml)
if ! docker compose ps --services 2>/dev/null | grep -qx "$SERVICE"; then
    cat <<EOF

Add this service to a docker-compose.override.yml, then run
'docker compose up -d && docker compose exec proxy nginx -s reload':

  $SERVICE:
    build:
      context: ./desktop
      args: { DESKTOP_USER: $USERNAME, ADMIN: "$( [[ $ROLE == admin ]] && echo 1 || echo 0 )" }
    image: cloudpc/$SERVICE
    restart: unless-stopped
    volumes: [ "home-$USERNAME:/home/$USERNAME" ]
    networks: [ ${USERNAME}_net ]
    tmpfs: [ "/tmp:size=512m", "/run:size=16m" ]
    shm_size: 1g
    security_opt: [no-new-privileges:true]   # remove for admin role (sudo)
    cap_drop: [ALL]
    mem_limit: 3g
    cpus: 2.0
    pids_limit: 1024

plus under the top-level keys:

  networks: { ${USERNAME}_net: {} }
  volumes:  { home-$USERNAME: {} }

and '${USERNAME}_net' appended to the proxy service's networks.
EOF
else
    docker compose exec proxy nginx -s reload
    echo "[add-user] Route active: https://<host>/desktop/$USERNAME/"
fi
