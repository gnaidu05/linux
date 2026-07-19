#!/usr/bin/env bash
#
# SecureOS image builder
#
# Produces a bootable hybrid BIOS/UEFI live ISO of a hardened Debian-based
# desktop OS with browsers, everyday applications, pre-configured users,
# and a full security stack. Run on a Debian/Ubuntu host as root:
#
#   sudo ./build.sh
#
# Output: out/secureos-<version>-<arch>.iso
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck source=config/build.conf
source "$SCRIPT_DIR/config/build.conf"

ROOTFS="$WORK_DIR/rootfs"
ISO_DIR="$WORK_DIR/iso"
ISO_NAME="secureos-${DISTRO_VERSION}-${ARCH}.iso"

log()  { printf '\e[1;32m[build]\e[0m %s\n' "$*"; }
die()  { printf '\e[1;31m[error]\e[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    [[ $EUID -eq 0 ]] || die "This script must run as root (it uses debootstrap and chroot)."
}

require_deps() {
    local deps=(debootstrap mksquashfs xorriso grub-mkstandalone mmd chroot)
    local missing=()
    for d in "${deps[@]}"; do
        command -v "$d" >/dev/null 2>&1 || missing+=("$d")
    done
    if ((${#missing[@]})); then
        die "Missing build tools: ${missing[*]}
Install with: apt-get install debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin mtools"
    fi
}

mount_pseudo_fs() {
    mount --bind /dev      "$ROOTFS/dev"
    mount --bind /dev/pts  "$ROOTFS/dev/pts"
    mount -t proc  proc    "$ROOTFS/proc"
    mount -t sysfs sysfs   "$ROOTFS/sys"
}

umount_pseudo_fs() {
    for m in dev/pts dev proc sys; do
        mountpoint -q "$ROOTFS/$m" && umount -lf "$ROOTFS/$m" || true
    done
}
trap umount_pseudo_fs EXIT

# ---------------------------------------------------------------------------
# Stage 1: bootstrap minimal Debian rootfs
# ---------------------------------------------------------------------------
stage_bootstrap() {
    if [[ -e "$ROOTFS/etc/os-release" ]]; then
        log "Rootfs already bootstrapped — skipping debootstrap (rm -rf $ROOTFS to force)."
        return
    fi
    log "Bootstrapping Debian $DEBIAN_SUITE ($ARCH) into $ROOTFS ..."
    mkdir -p "$ROOTFS"
    debootstrap --arch="$ARCH" --variant=minbase "$DEBIAN_SUITE" "$ROOTFS" "$DEBIAN_MIRROR"
}

# ---------------------------------------------------------------------------
# Stage 2: copy configuration into the rootfs
# ---------------------------------------------------------------------------
stage_configure() {
    log "Copying package lists, config files, and chroot scripts ..."

    # Overlay static config files (sysctl, sshd, PAM, audit, fail2ban, ...)
    cp -a "$SCRIPT_DIR/files/." "$ROOTFS/"

    # Build-time inputs for the chroot scripts
    mkdir -p "$ROOTFS/tmp/secureos"
    cp -a "$SCRIPT_DIR/config" "$ROOTFS/tmp/secureos/config"
    cp -a "$SCRIPT_DIR/scripts/chroot" "$ROOTFS/tmp/secureos/scripts"
    cp -a "$SCRIPT_DIR/installer" "$ROOTFS/tmp/secureos/installer"

    # APT sources with security updates
    cat > "$ROOTFS/etc/apt/sources.list" <<EOF
deb $DEBIAN_MIRROR $DEBIAN_SUITE main contrib non-free-firmware
deb $DEBIAN_MIRROR ${DEBIAN_SUITE}-updates main contrib non-free-firmware
deb $DEBIAN_SECURITY_MIRROR ${DEBIAN_SUITE}-security main contrib non-free-firmware
EOF

    echo "$DISTRO_HOSTNAME" > "$ROOTFS/etc/hostname"
    cat > "$ROOTFS/etc/hosts" <<EOF
127.0.0.1   localhost
127.0.1.1   $DISTRO_HOSTNAME
::1         localhost ip6-localhost ip6-loopback
EOF

    cat > "$ROOTFS/etc/os-release" <<EOF
PRETTY_NAME="$DISTRO_NAME $DISTRO_VERSION"
NAME="$DISTRO_NAME"
VERSION_ID="$DISTRO_VERSION"
ID=secureos
ID_LIKE=debian
HOME_URL="https://github.com/gnaidu05/linux"
EOF
}

# ---------------------------------------------------------------------------
# Stage 3: run provisioning scripts inside the chroot
# ---------------------------------------------------------------------------
stage_provision() {
    log "Running chroot provisioning scripts ..."
    mount_pseudo_fs

    # Prevent services from starting inside the chroot
    cat > "$ROOTFS/usr/sbin/policy-rc.d" <<'EOF'
#!/bin/sh
exit 101
EOF
    chmod +x "$ROOTFS/usr/sbin/policy-rc.d"

    for script in "$SCRIPT_DIR"/scripts/chroot/*.sh; do
        local name
        name="$(basename "$script")"
        log "  -> $name"
        chroot "$ROOTFS" /bin/bash "/tmp/secureos/scripts/$name"
    done

    rm -f "$ROOTFS/usr/sbin/policy-rc.d"
    rm -rf "$ROOTFS/tmp/secureos"
    umount_pseudo_fs
}

# ---------------------------------------------------------------------------
# Stage 4: squashfs + bootloader + hybrid ISO
# ---------------------------------------------------------------------------
stage_image() {
    log "Building squashfs ..."
    mkdir -p "$ISO_DIR/live" "$ISO_DIR/boot/grub" "$OUT_DIR"

    # Kernel and initrd out of the rootfs
    cp "$ROOTFS"/boot/vmlinuz-*    "$ISO_DIR/live/vmlinuz"
    cp "$ROOTFS"/boot/initrd.img-* "$ISO_DIR/live/initrd"

    rm -f "$ISO_DIR/live/filesystem.squashfs"
    mksquashfs "$ROOTFS" "$ISO_DIR/live/filesystem.squashfs" \
        -comp zstd -Xcompression-level 19 -e boot

    log "Installing GRUB (BIOS + UEFI) ..."
    cat > "$ISO_DIR/boot/grub/grub.cfg" <<EOF
set default=0
set timeout=5

menuentry "$DISTRO_NAME $DISTRO_VERSION (Live)" {
    linux /live/vmlinuz boot=live quiet splash
    initrd /live/initrd
}
menuentry "$DISTRO_NAME $DISTRO_VERSION (Live, safe graphics)" {
    linux /live/vmlinuz boot=live nomodeset
    initrd /live/initrd
}
menuentry "$DISTRO_NAME $DISTRO_VERSION (Live, to RAM)" {
    linux /live/vmlinuz boot=live toram quiet
    initrd /live/initrd
}
EOF

    # UEFI: standalone GRUB EFI binary inside a small FAT image
    grub-mkstandalone \
        --format=x86_64-efi \
        --output="$WORK_DIR/bootx64.efi" \
        --locales="" --fonts="" \
        "boot/grub/grub.cfg=$ISO_DIR/boot/grub/grub.cfg"

    dd if=/dev/zero of="$WORK_DIR/efiboot.img" bs=1M count=8 status=none
    mkfs.vfat "$WORK_DIR/efiboot.img" >/dev/null
    mmd -i "$WORK_DIR/efiboot.img" efi efi/boot
    mcopy -i "$WORK_DIR/efiboot.img" "$WORK_DIR/bootx64.efi" ::efi/boot/bootx64.efi

    # BIOS: eltorito image
    grub-mkstandalone \
        --format=i386-pc \
        --output="$WORK_DIR/core.img" \
        --install-modules="linux normal iso9660 biosdisk memdisk search tar ls" \
        --modules="linux normal iso9660 biosdisk search" \
        --locales="" --fonts="" \
        "boot/grub/grub.cfg=$ISO_DIR/boot/grub/grub.cfg"

    cat /usr/lib/grub/i386-pc/cdboot.img "$WORK_DIR/core.img" \
        > "$ISO_DIR/boot/grub/bios.img"

    log "Assembling hybrid ISO ..."
    xorriso -as mkisofs \
        -iso-level 3 \
        -volid "$ISO_LABEL" \
        -full-iso9660-filenames \
        -eltorito-boot boot/grub/bios.img \
        -no-emul-boot -boot-load-size 4 -boot-info-table \
        --eltorito-catalog boot/grub/boot.cat \
        --grub2-boot-info \
        --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img \
        -eltorito-alt-boot \
        -e --interval:appended_partition_2:all:: \
        -append_partition 2 0xef "$WORK_DIR/efiboot.img" \
        -no-emul-boot \
        -o "$OUT_DIR/$ISO_NAME" \
        "$ISO_DIR"

    log "Done: $OUT_DIR/$ISO_NAME"
    log "Test with: qemu-system-x86_64 -m 4096 -enable-kvm -cdrom $OUT_DIR/$ISO_NAME"
}

main() {
    require_root
    require_deps
    mkdir -p "$WORK_DIR" "$OUT_DIR"
    stage_bootstrap
    stage_configure
    stage_provision
    stage_image
}

main "$@"
