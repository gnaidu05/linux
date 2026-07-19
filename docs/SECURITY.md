# SecureOS security architecture

This document describes every security control baked into the image, where it
is configured, and why.

## 1. Users and authentication

| Control | Configuration |
|---------|---------------|
| Root account **locked** | `passwd -l root` (`scripts/chroot/20-users-auth.sh`) — all privileged work via sudo |
| Least-privilege accounts | `admin` in `sudo`+`adm`; `user` unprivileged (`config/users.conf`) |
| Forced password change at first login | `chage -d 0` on every baked-in account |
| Password quality | `pam_pwquality`: min 12 chars, 4 character classes, no repeats/sequences (`files/etc/security/pwquality.conf`) |
| Account lockout | `pam_faillock`: 5 failures → 15-minute lock, root included (`files/etc/security/faillock.conf`) |
| Password aging | max 365 days, min 1 day, 14-day warning (`login.defs`) |
| Strong password hashing | yescrypt/SHA-512 with ≥100k rounds (`login.defs`) |
| Private home directories | `chmod 750`, default umask `027` |
| `su` restricted | `pam_wheel`: only members of group `sudo` may use `su` |

## 2. Privilege escalation (sudo)

`files/etc/sudoers.d/50-secureos`:

- Full **I/O logging** (`log_input`, `log_output`) to `/var/log/sudo-io`
- Command log at `/var/log/sudo.log`
- `use_pty` (defeats tty hijacking), 5-minute credential cache
- Policy validated with `visudo -cf` at build time

## 3. Network security

- **UFW firewall**: default **deny incoming / allow outgoing**, logging on.
  No inbound service is reachable out of the box.
- **SSH server installed but disabled.** If enabled, hardened by
  `files/etc/ssh/sshd_config.d/99-secureos.conf`: no root login, max 3 auth
  tries, modern KEX/ciphers/MACs only, no agent/TCP/X11 forwarding, login
  banner. Recommended: `ufw limit ssh` + key-only auth.
- **fail2ban**: sshd (aggressive mode) and pam-generic jails, 1-hour bans via
  UFW (`files/etc/fail2ban/jail.local`).
- **sysctl network hardening**: syncookies, reverse-path filtering, all
  redirects/source-routing rejected, martian logging, forwarding off
  (`files/etc/sysctl.d/99-secureos.conf`).

## 4. Kernel and platform hardening

- **AppArmor** enforced with extra profiles (`apparmor-profiles`, `apparmor-utils`)
- **Kernel command line** on installed systems: `lockdown=integrity`,
  `slab_nomerge`, `init_on_alloc=1 init_on_free=1`, `page_alloc.shuffle=1`,
  `randomize_kstack_offset=on` (set by the installer)
- **sysctl kernel hardening**: `kptr_restrict=2`, `dmesg_restrict=1`,
  unprivileged BPF disabled + JIT hardening, `ptrace_scope=1`, kexec disabled,
  SysRq off, `perf_event_paranoid=3`, full ASLR, userfaultfd restricted
- **Module blacklist**: uncommon network protocols (DCCP/SCTP/RDS/TIPC),
  legacy filesystems, FireWire DMA (`files/etc/modprobe.d/99-secureos-blacklist.conf`)
- **Core dumps disabled** for setuid programs; `core_pattern` neutered
- **Filesystem protections**: protected symlinks/hardlinks/FIFOs/regular files
- **Secure Boot–compatible boot chain**: `shim-signed` + `grub-efi-amd64-signed`

## 5. Auditing and monitoring

- **auditd** with rules covering identity files, PAM, sudoers, SSH config,
  privileged execution, module loading, time changes, mounts, and deletions
  (`files/etc/audit/rules.d/99-secureos.rules`); rules immutable until reboot (`-e 2`)
- **sudo I/O session recording** (see §2)
- **rkhunter + chkrootkit** installed for rootkit scans
- **ClamAV** with automatic signature updates (freshclam); on-demand scanning

## 6. Updates and supply chain

- **unattended-upgrades**: security updates applied automatically daily,
  unused kernels/dependencies removed (`files/etc/apt/apt.conf.d/50unattended-upgrades`)
- **needrestart** flags services running outdated libraries
- APT sources include `bookworm-security` and `bookworm-updates`

## 7. Data at rest

- The installer (`secureos-install`) creates **LUKS2 full-disk encryption**
  with argon2id key derivation and AES-XTS-512
- `/tmp` is tmpfs (`nosuid,nodev`); `libpam-tmpdir` gives each user a private
  temp directory
- ESP mounted `umask=0077`

## 8. Image hygiene

- `/etc/machine-id` blanked — regenerated uniquely on first boot
- **No SSH host keys in the image** — regenerated on first boot by a oneshot
  systemd unit, so every install has unique keys
- cron/at restricted to root; login banners on console and SSH
- Stray setuid bits removed (`wall`, `write`)

## 9. Known trade-offs

- `PasswordAuthentication yes` is kept for SSH so a fresh install is usable;
  switch to key-only (`PasswordAuthentication no`) once keys are deployed.
- ClamAV's on-access daemon is off by default (RAM cost); freshclam still
  updates signatures for on-demand scans.
- AIDE file-integrity checking is available but off by default
  (`ENABLE_AIDE` in `config/build.conf`) because database initialization is slow.
- The live ISO itself is unencrypted by design; encryption applies to
  installed systems.
