#!/usr/bin/env bash
#
# SecureOS disk installer — run from the live session as root:
#   sudo secureos-install /dev/sdX
#
# Installs the running live system to the target disk with:
#   - GPT partitioning (EFI system partition + LUKS2-encrypted root)
#   - Full-disk encryption (LUKS2, argon2id) — passphrase chosen interactively
#   - ext4 root filesystem, GRUB for UEFI and BIOS
#
# WARNING: this ERASES the target disk.
#
set -euo pipefail

DISK="${1:-}"
LIVE_ROOT="/run/live/rootfs/filesystem.squashfs"

die() { echo "error: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo secureos-install /dev/sdX)"
[[ -n "$DISK" ]] || die "usage: secureos-install /dev/sdX"
[[ -b "$DISK" ]] || die "$DISK is not a block device"
[[ -d "$LIVE_ROOT" ]] || die "not running from a SecureOS live session"

echo "==============================================================="
echo " SecureOS installer"
echo " Target disk: $DISK  ($(lsblk -ndo SIZE "$DISK") )"
echo
echo " ALL DATA ON $DISK WILL BE DESTROYED."
echo "==============================================================="
read -rp "Type 'ERASE' to continue: " confirm
[[ "$confirm" == "ERASE" ]] || die "aborted"

# Partition suffix for nvme/mmc devices (p1/p2 vs 1/2)
PART=""
[[ "$DISK" =~ (nvme|mmcblk|loop) ]] && PART="p"

echo "[1/6] Partitioning $DISK (GPT: BIOS-boot + ESP + LUKS root) ..."
sgdisk --zap-all "$DISK"
sgdisk -n1:0:+1M   -t1:EF02 -c1:"BIOS boot" "$DISK"
sgdisk -n2:0:+512M -t2:EF00 -c2:"EFI System" "$DISK"
sgdisk -n3:0:0     -t3:8309 -c3:"SecureOS LUKS" "$DISK"
partprobe "$DISK"; sleep 2

ESP="${DISK}${PART}2"
LUKS_PART="${DISK}${PART}3"

echo "[2/6] Setting up LUKS2 full-disk encryption on $LUKS_PART ..."
echo "Choose a strong disk encryption passphrase (asked twice):"
cryptsetup luksFormat --type luks2 --pbkdf argon2id \
    --cipher aes-xts-plain64 --key-size 512 --verify-passphrase "$LUKS_PART"
cryptsetup open "$LUKS_PART" secureos_root

echo "[3/6] Creating filesystems ..."
mkfs.vfat -F32 -n EFI "$ESP"
mkfs.ext4 -L secureos-root /dev/mapper/secureos_root

MNT=/mnt/secureos-install
mkdir -p "$MNT"
mount /dev/mapper/secureos_root "$MNT"
mkdir -p "$MNT/boot/efi"
mount "$ESP" "$MNT/boot/efi"

echo "[4/6] Copying system (this takes a few minutes) ..."
rsync -aHAX --info=progress2 \
    --exclude={"/proc/*","/sys/*","/dev/*","/run/*","/tmp/*","/mnt/*","/media/*","/lost+found"} \
    "$LIVE_ROOT/" "$MNT/"

echo "[5/6] Configuring the installed system ..."
LUKS_UUID="$(blkid -s UUID -o value "$LUKS_PART")"
ROOT_UUID="$(blkid -s UUID -o value /dev/mapper/secureos_root)"
ESP_UUID="$(blkid -s UUID -o value "$ESP")"

cat > "$MNT/etc/fstab" <<EOF
UUID=$ROOT_UUID  /          ext4  defaults,errors=remount-ro           0 1
UUID=$ESP_UUID   /boot/efi  vfat  umask=0077                           0 2
tmpfs            /tmp       tmpfs defaults,nosuid,nodev,mode=1777      0 0
EOF

cat > "$MNT/etc/crypttab" <<EOF
secureos_root UUID=$LUKS_UUID none luks,discard
EOF

# Remove live-boot packages and set hardened kernel cmdline
for fs in dev dev/pts proc sys; do mount --bind "/$fs" "$MNT/$fs"; done

mkdir -p "$MNT/etc/default/grub.d"
cat > "$MNT/etc/default/grub.d/99-secureos.cfg" <<'EOF'
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"
GRUB_CMDLINE_LINUX="apparmor=1 security=apparmor lockdown=integrity slab_nomerge init_on_alloc=1 init_on_free=1 page_alloc.shuffle=1 randomize_kstack_offset=on"
GRUB_ENABLE_CRYPTODISK=y
EOF

chroot "$MNT" /bin/bash -euo pipefail <<CHROOT
export DEBIAN_FRONTEND=noninteractive
apt-get purge -y live-boot live-config 2>/dev/null || true
update-initramfs -u -k all
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=SecureOS --recheck || true
grub-install --target=i386-pc "$DISK" || true
update-grub
CHROOT

for fs in dev/pts dev proc sys; do umount -lf "$MNT/$fs" || true; done

echo "[6/6] Finishing ..."
umount -R "$MNT"
cryptsetup close secureos_root

echo
echo "Installation complete. Remove the live media and reboot."
echo "Log in as 'admin' — you will be forced to set a new password."
