# CloudPC reverse proxy — nginx from Ubuntu archives.
# TLS termination, auth_request gate in front of every desktop, websocket
# proxying for VNC. Runs read-only with a tmpfs for runtime state.
FROM cloudpc/base:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends nginx-core && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    rm /etc/nginx/sites-enabled/default

COPY nginx.conf /etc/nginx/nginx.conf
COPY cloudpc.conf /etc/nginx/conf.d/cloudpc.conf

# Desktop routes are generated per user by scripts/add-user.sh into
# conf.d/desktops/ (mounted from the host).
RUN mkdir -p /etc/nginx/conf.d/desktops

EXPOSE 8443
CMD ["nginx", "-g", "daemon off;"]
