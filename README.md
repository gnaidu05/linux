# SecureOS — a hardened, fully functional Linux desktop OS

SecureOS is a complete, reproducible build system that produces a **bootable
hybrid BIOS/UEFI Linux ISO** based on Debian 12 (bookworm), with:

- **Desktop environment** — XFCE by default (GNOME available via one config line)
- **Browsers** — Firefox ESR and Chromium (with sandbox)
- **Everyday applications** — LibreOffice, Thunderbird, VLC, GIMP, KeePassXC,
  Evince, GParted, Transmission, Remmina, Flameshot, and more
- **Security stack** — UFW firewall (default-deny), AppArmor, auditd, fail2ban,
  automatic security updates, kernel/sysctl hardening, ClamAV, module blacklist
- **Authentication & users** — pre-configured `admin` (sudo) and `user`
  accounts, locked root, PAM password quality + account lockout, forced
  password change on first login, hardened sudo with I/O logging
- **Installer** — `secureos-install` installs to disk with LUKS2 full-disk
  encryption (argon2id) and a hardened kernel command line

## Quick start

Build on any Debian 12 / Ubuntu 22.04+ host (or container with `--privileged`):

```bash
sudo apt-get install debootstrap squashfs-tools xorriso \
     grub-pc-bin grub-efi-amd64-bin mtools dosfstools
sudo ./build.sh
```

Output: `out/secureos-1.0-amd64.iso` (~3–4 GB). Test it:

```bash
qemu-system-x86_64 -m 4096 -enable-kvm -cdrom out/secureos-1.0-amd64.iso
```

Write to a USB stick (the ISO is hybrid — bootable on BIOS and UEFI):

```bash
sudo dd if=out/secureos-1.0-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

## Logging in

| Account | Role | Initial password |
|---------|------|------------------|
| `admin` | Administrator (sudo) | `ChangeMe!2026` |
| `user`  | Standard user | `ChangeMe!2026` |
| `root`  | **Locked** — use `sudo` | — |

Both accounts are **forced to set a new password at first login**. New
passwords must be ≥12 characters with upper/lower/digit/symbol
(see `files/etc/security/pwquality.conf`).

## Installing to disk

From the live session:

```bash
sudo secureos-install /dev/sdX    # ERASES the disk; prompts for confirmation
```

The installer sets up GPT partitioning, a LUKS2-encrypted root (you choose the
passphrase), installs GRUB for both BIOS and UEFI, and enables the hardened
kernel command line (AppArmor, lockdown, init_on_alloc/free, etc.).

## Customizing

| What | Where |
|------|-------|
| Distro name/version, mirror, desktop choice | `config/build.conf` |
| User accounts and roles | `config/users.conf` |
| Package selection | `config/packages/*.list` |
| Security policies (sysctl, SSH, PAM, audit, fail2ban, sudo) | `files/etc/...` |
| Provisioning logic | `scripts/chroot/*.sh` |

Set `DESKTOP="gnome"` in `config/build.conf` for a GNOME desktop instead of XFCE.

## Repository layout

```
build.sh                    Top-level orchestrator (debootstrap → provision → ISO)
config/build.conf           Build settings
config/users.conf           Declarative user accounts
config/packages/*.list      Package sets (base, desktop, browsers, apps, security)
scripts/chroot/             Provisioning scripts run inside the rootfs
  10-packages.sh              install everything
  20-users-auth.sh            users, PAM, sudo, lockout policy
  30-security-hardening.sh    firewall, AppArmor, auditd, fail2ban, updates
  40-cleanup.sh               shrink image, reset machine identity
files/                      Config overlay copied verbatim into the rootfs
installer/install-to-disk.sh  LUKS2 full-disk-encryption installer
docs/SECURITY.md            Full security architecture documentation
```

See [docs/SECURITY.md](docs/SECURITY.md) for the complete security model.
