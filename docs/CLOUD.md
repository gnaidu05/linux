# Running SecureOS in the browser (cloud deployment)

SecureOS can run as a **cloud desktop**: the OS runs on a server under
QEMU/KVM and the full desktop is streamed to any web browser via
[noVNC](https://novnc.com) over HTTPS. Nothing to install on the client —
open a URL, enter the password, and you're at the SecureOS desktop.

```
 ┌─────────┐   HTTPS / WSS    ┌──────────────────────┐   localhost    ┌────────────┐
 │ Browser ├─────────────────>│ websockify + noVNC   ├───────────────>│ QEMU / KVM │
 │ (any)   │   TLS, :6080     │ (public, TLS)        │  VNC :5900     │  SecureOS  │
 └─────────┘                  └──────────────────────┘  (password)    └────────────┘
```

Two layers of protection sit in front of the desktop: TLS on the public
port, and a VNC password (auto-generated, set over QMP so it never appears
in the process list). QEMU's VNC listens on **127.0.0.1 only** — it is never
directly reachable from the network.

## Why not run it *inside* the browser?

In-browser x86 emulators (v86, JSLinux) emulate a 32-bit, Pentium-era CPU
with no KVM. A modern 64-bit desktop OS with XFCE, Firefox, and LibreOffice
will not boot there, and never usably. The cloud + noVNC model gives you a
real, full-speed OS with the browser as a thin client — the same model
commercial "cloud PC" products use.

## Quick start

On any cloud VM (Hetzner, DigitalOcean, OVH, EC2, GCP — pick one with
KVM/nested-virt; 2+ vCPU, 8 GB RAM recommended):

```bash
git clone <this-repo> secureos && cd secureos

# 1. One-time host setup: QEMU/KVM, noVNC, firewall
sudo ./cloud/provision-server.sh

# 2. Get the ISO: build it here (sudo ./build.sh) or scp it from elsewhere

# 3. First boot: live ISO with a 40G persistent disk attached
sudo ./cloud/run-cloud.sh --iso out/secureos-1.0-amd64.iso --disk secureos.qcow2
```

Open `https://<server-ip>:6080/vnc.html`, accept the self-signed
certificate warning, and enter the VNC password the script printed
(also saved in `cloud/state/vnc-password`).

Inside the browser session, install the OS to the virtual disk with full
disk encryption:

```bash
sudo secureos-install /dev/vda
```

Then shut down and from now on boot the installed system directly:

```bash
sudo ./cloud/stop-cloud.sh
sudo ./cloud/run-cloud.sh --disk secureos.qcow2
```

## Run as a service (boot on server start)

```bash
sudo mkdir -p /opt/secureos && sudo cp -a . /opt/secureos
sudo cp cloud/secureos-cloud.service /etc/systemd/system/
sudo systemctl enable --now secureos-cloud
```

## Tuning

Environment variables understood by `run-cloud.sh`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `RAM_MB` | 4096 | Guest RAM |
| `CPUS` | 2 | Guest vCPUs |
| `DISK_SIZE` | 40G | Size when creating a new `--disk` file |
| `HTTP_PORT` | 6080 | Public noVNC HTTPS port |
| `VNC_PASSWORD` | auto | Override the generated VNC password |
| `STATE_DIR` | `cloud/state` | Certs, password, sockets, pidfile |

## Hardening the public endpoint

- **Trusted TLS**: replace the self-signed cert with a real one —
  point a DNS name at the server, get a certificate
  (`certbot certonly --standalone -d desktop.example.com`), then set
  `CERT`/`KEY` paths in `run-cloud.sh`'s state dir (or symlink
  `cloud/state/novnc-cert.pem` / `novnc-key.pem` to the Let's Encrypt files).
- **Restrict access by IP**: `ufw allow from <your-ip> to any port 6080`
  instead of the open rule, or skip the public port entirely and use an
  SSH tunnel: `ssh -L 6080:localhost:6080 user@server`, then browse to
  `https://localhost:6080/vnc.html`.
- **VNC password rotation**: `rm cloud/state/vnc-password` and restart —
  a new one is generated.
- Remember the OS itself still enforces its own login (user passwords,
  lockout, etc.) — the VNC password only gates access to the console,
  exactly like physical access to a screen.

## Verified

The QEMU → QMP password → websockify/TLS → noVNC pipeline in this repo was
smoke-tested end to end (VM boot, RFB handshake on localhost:5900, HTTPS 200
on `/vnc.html`, graceful stop). Only the SecureOS ISO itself needs to be
supplied by `build.sh`.
