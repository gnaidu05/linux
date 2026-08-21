# CloudPC desktop session image
#
# XFCE desktop delivered to the browser via TigerVNC (Xvnc) + noVNC.
# Runs entirely as an unprivileged user; the web auth layer (nginx + auth
# portal) sits in front — this container is never directly exposed.
#
# Browsers (Ubuntu ships both only as snaps, which cannot run in a
# container, so both come from real .deb sources):
#   - Chromium: from the xtradeb PPA (real .deb). If that PPA is
#     unreachable at build time, an optional vendored build copied into
#     the image (desktop/vendor/chromium, populated by
#     scripts/fetch-chromium.sh) is used as a fallback.
#   - Firefox:  from the Mozilla Team PPA (real .deb).
# Each browser install is best-effort: if its repo is unreachable the build
# continues and records the skip in /etc/cloudpc/build-warnings. The wrapper
# /usr/local/bin/chromium prefers the vendored build, else the apt one.
FROM cloudpc/base:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Desktop environment + display stack + required applications.
# XFCE chosen over KDE: ~1/3 the RAM per session, renders well over VNC
# (solid colors, no compositing effects), and is fully functional.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xfce4 xfce4-terminal xfce4-taskmanager thunar thunar-archive-plugin \
        mousepad ristretto xarchiver galculator \
        tigervnc-standalone-server tigervnc-tools novnc python3-websockify \
        dbus-x11 at-spi2-core xdg-utils xdg-user-dirs \
        fonts-dejavu fonts-liberation fonts-noto-core \
        libreoffice-writer libreoffice-calc libreoffice-impress libreoffice-gtk3 \
        vlc gimp \
        sudo ca-certificates curl less vim-tiny bash-completion && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# --- Browsers from real .deb PPAs (best effort; see header) ----------------
RUN set -e; mkdir -p /etc/cloudpc; \
    apt-get update 2>/dev/null && \
    apt-get install -y --no-install-recommends software-properties-common 2>/dev/null || true; \
    # Firefox (Mozilla Team PPA)
    if add-apt-repository -y ppa:mozillateam/ppa 2>/dev/null && \
       printf 'Package: firefox*\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n' \
            > /etc/apt/preferences.d/mozilla-ppa && \
       apt-get update 2>/dev/null && \
       apt-get install -y --no-install-recommends firefox 2>/dev/null; then \
        echo "firefox: installed from mozillateam PPA" >> /etc/cloudpc/build-info; \
    else \
        echo "WARNING firefox skipped: mozillateam PPA unreachable at build time" \
            >> /etc/cloudpc/build-warnings; \
    fi; \
    # Chromium (xtradeb PPA — real .deb, not the Ubuntu snap shim)
    if add-apt-repository -y ppa:xtradeb/apps 2>/dev/null && \
       apt-get update 2>/dev/null && \
       apt-get install -y --no-install-recommends chromium 2>/dev/null; then \
        echo "chromium: installed from xtradeb PPA" >> /etc/cloudpc/build-info; \
    else \
        echo "WARNING chromium apt install skipped: xtradeb PPA unreachable; \
using vendored build if present" >> /etc/cloudpc/build-warnings; \
    fi; \
    apt-get clean; rm -rf /var/lib/apt/lists/*

# --- Optional vendored Chromium (offline fallback) -------------------------
# desktop/vendor/chromium holds only a .gitkeep in the repo; a full build is
# dropped in by scripts/fetch-chromium.sh for offline/air-gapped builds.
# Runtime libs so a vendored (apt-independent) Chromium can start:
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
        libgbm1 libasound2t64 libpango-1.0-0 libcairo2 libgtk-3-0t64 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
COPY vendor/chromium/ /opt/chromium/
COPY chromium.sh /usr/local/bin/chromium
COPY chromium.desktop /usr/share/applications/chromium.desktop
RUN chmod 755 /usr/local/bin/chromium && chmod -R a+rX /opt/chromium 2>/dev/null || true

# --- Session user ----------------------------------------------------------
# DESKTOP_USER is the login name; ADMIN=1 grants sudo (password required).
# The admin's unix password (for sudo) comes from a BuildKit secret so it
# never appears in image history:  --secret id=unix_password,src=...
ARG DESKTOP_USER=user
ARG ADMIN=0
RUN --mount=type=secret,id=unix_password,required=false \
    set -e; \
    useradd -m -u 1000 -s /bin/bash "$DESKTOP_USER"; \
    passwd -l root; \
    if [ "$ADMIN" = "1" ]; then \
        usermod -aG sudo "$DESKTOP_USER"; \
        if [ -s /run/secrets/unix_password ]; then \
            echo "$DESKTOP_USER:$(cat /run/secrets/unix_password)" | chpasswd; \
        fi; \
        printf 'Defaults use_pty\nDefaults passwd_timeout=1\nDefaults timestamp_timeout=5\n' \
            > /etc/sudoers.d/50-cloudpc; chmod 440 /etc/sudoers.d/50-cloudpc; \
    else \
        rm -f /etc/sudoers.d/*; \
    fi

COPY startup.sh /usr/local/bin/cloudpc-session
RUN chmod 755 /usr/local/bin/cloudpc-session

ENV DESKTOP_USER=$DESKTOP_USER \
    DISPLAY_GEOMETRY=1600x900 \
    HOME_DIR=/home/$DESKTOP_USER

USER $DESKTOP_USER
WORKDIR /home/$DESKTOP_USER
EXPOSE 6901
ENTRYPOINT ["/usr/local/bin/cloudpc-session"]
