#!/usr/bin/env bash
#
# prep-sd-card.sh — stage a Raspberry Pi OS (32-bit / Trixie Lite) *image file*
# for the Resistor-Reader appliance on a Pi Zero, doing all the slow work
# (apt full-upgrade, package install, pip builds) here on a fast machine via a
# qemu-arm chroot on a loop device — so every write lands on this laptop's disk
# instead of a slow microSD card. Output is a staged .img you flash in one pass.
#
# Usage:
#   sudo IMG=~/Downloads/2026-06-18-raspios-trixie-armhf-lite.img.xz \
#        ./prep-sd-card.sh
#
#   IMG       required — a Raspberry Pi OS Lite .img or .img.xz (from rpi.org)
#   WORK_IMG  the staged image to build/flash (default: IMG with .xz stripped,
#             or "<name>-appliance.img" for a plain .img — the pristine download
#             is never modified)
#   IMG_SIZE  grow the work image to this before the chroot (default 6G); needs
#             headroom for apt full-upgrade + opencv/scipy
#   FRESH=1        re-decompress / re-copy even if WORK_IMG already exists
#   FULL_UPGRADE=0 skip `apt full-upgrade` — avoids a kernel bump; base stays at
#                  the image's release date (upgrade later on the Pi)
#   KEEP_KERNELS   kernel flavours to keep, space-separated (default "v6" for the
#                  original Pi Zero / Zero W; "v7 v8" for a Zero 2 W; "" = keep
#                  all). Purging the rest is the single biggest speed-up: each
#                  unused flavour is a ~50 s emulated initramfs build.
#   APT_CACHE      host dir for a persistent .deb cache across runs
#                  (default: <WORK_IMG dir>/.prep-sd-apt-cache)
#   BRANCH         Resistor-Reader branch to check out (default claude-rewrite)
#   REPO           clone URL
#
# Everything in the chroot runs as emulated 32-bit ARM (qemu-user), which is
# CPU-bound and ~5-10x slower than native — so the build defers initramfs to one
# run per kept kernel, purges unused kernel flavours, drops superseded kernels,
# skips man-db/doc, disables dpkg fsync, and denies service starts.
#
# Result (baked into WORK_IMG):
#   * user "pi" / password "raspberry" (defaults), SSH enabled, no setup wizard
#   * USB OTG gadget ethernet (CDC-NCM, built with configfs/libcomposite): plug
#     the Pi's data port into this PC, give the PC 10.42.0.2/24 on the gadget
#     link, then `ssh pi@10.42.0.1`. The Pi holds a static 10.42.0.1/24, brought
#     up by usb-gadget-ncm.service before NetworkManager starts. NCM (not the
#     legacy g_ether/CDC-ECM gadget) because ECM's bulk TX path stalls against
#     many xHCI hosts ("cdc_ether ... NETDEV WATCHDOG: transmit queue timed out").
#   * all README apt packages + i2c-tools installed (and upgraded unless
#     FULL_UPGRADE=0)
#   * Resistor-Reader cloned at /home/pi/Resistor-Reader on branch claude-rewrite
#   * .venv (system-site-packages) with adafruit-circuitpython-ht16k33
#   * i2c enabled; debug JPEG writes disabled in config.yaml
#   * first boot on the real card auto-expands the rootfs to fill it
#   * read-only root: NOT enabled here (see note at end) — one command on the Pi
#
# Run as root.
set -euo pipefail

IMG=${IMG:?set IMG=/path/to/raspios-...-lite.img[.xz]}
if [[ $IMG == *.xz ]]; then
  WORK_IMG=${WORK_IMG:-${IMG%.xz}}
else
  WORK_IMG=${WORK_IMG:-${IMG%.img}-appliance.img}
fi
IMG_SIZE=${IMG_SIZE:-6G}
FRESH=${FRESH:-0}
FULL_UPGRADE=${FULL_UPGRADE:-1}   # 0 = skip apt full-upgrade (no kernel bump -> much faster)
# kernel flavours to keep (space-separated); the rest are purged so their
# initramfs is never built under qemu (the slowest part of the run).
# original Pi Zero / Zero W is ARMv6 -> "v6"; Pi Zero 2 W -> "v7 v8"; ""=keep all
KEEP_KERNELS=${KEEP_KERNELS:-v6}
# persistent .deb cache on the host, bind-mounted into the chroot so re-runs
# don't re-download; never ends up in the flashed image (unmounted first)
APT_CACHE=${APT_CACHE:-$(dirname "$WORK_IMG")/.prep-sd-apt-cache}
BRANCH=${BRANCH:-claude-rewrite}
REPO=${REPO:-https://github.com/ericboehlke/Resistor-Reader.git}

APT_PKGS=(
  git python3-pip
  python3-rpi.gpio python3-picamera2 python3-opencv
  python3-pil python3-yaml python3-pytest
  i2c-tools
)
# No build-essential / python3-dev: the venv pip step installs only pure-Python
# and prebuilt piwheels wheels, so nothing is compiled on the appliance. Add
# EXTRA_APT_PKGS=... at runtime if a future dependency needs a toolchain.
APT_PKGS+=(${EXTRA_APT_PKGS:-})

# --- pretty output ----------------------------------------------------------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; BLUE=$'\033[1;34m'; GREEN=$'\033[1;32m'
  YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
  BOLD='' BLUE='' GREEN='' YELLOW='' RED='' DIM='' RESET=''
fi
STEP_N=0
step()  { STEP_N=$((STEP_N + 1)); printf '\n%s━━━ [%d] %s ━━━%s\n' "$BLUE" "$STEP_N" "$*" "$RESET"; }
info()  { printf '    %s\n' "$*"; }
ok()    { printf '%s    ✓ %s%s\n' "$GREEN" "$*" "$RESET"; }
warn()  { printf '%s    ! %s%s\n' "$YELLOW" "$*" "$RESET"; }
die()   { printf '%s✗ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

# --- [1] preflight ----------------------------------------------------------
step "Preflight checks"
[[ $EUID -eq 0 ]] || die "must run as root"
[[ -f "$IMG" ]] || die "IMG not found: $IMG"
need=(losetup parted partprobe e2fsck resize2fs truncate udevadm openssl blockdev sha256sum findmnt)
[[ $IMG == *.xz ]] && need+=(xz)
for t in "${need[@]}"; do
  command -v "$t" >/dev/null || die "missing required tool: $t"
done
command -v qemu-arm-static >/dev/null || command -v qemu-arm >/dev/null || \
  die "install qemu-user-static (+ binfmt) first"
ok "tooling present, IMG readable"

# --- [2] configuration ----------------------------------------------------------
step "Configuration"
printf '%s' "$DIM"
cat <<EOF
    IMG          = $IMG
    WORK_IMG     = $WORK_IMG
    IMG_SIZE     = $IMG_SIZE
    FRESH        = $FRESH
    FULL_UPGRADE = $FULL_UPGRADE
    KEEP_KERNELS = ${KEEP_KERNELS:-<all>}
    APT_CACHE    = $APT_CACHE
    BRANCH       = $BRANCH
    REPO         = $REPO
    APT_PKGS     = ${APT_PKGS[*]}
EOF
printf '%s' "$RESET"

# --- [3] prepare the work image --------------------------------------------------
step "Prepare work image"
if [[ "$IMG" -ef "$WORK_IMG" ]]; then
  die "IMG and WORK_IMG are the same file — refusing to modify the source in place"
fi
if [[ -f "$WORK_IMG" && "$FRESH" != 1 ]]; then
  info "$WORK_IMG exists — reusing (FRESH=1 to rebuild it from IMG)"
elif [[ $IMG == *.xz ]]; then
  info "decompressing $IMG -> $WORK_IMG"
  xz -dc -T0 "$IMG" > "$WORK_IMG"
else
  info "copying $IMG -> $WORK_IMG"
  cp --reflink=auto "$IMG" "$WORK_IMG"
fi
# grow only — '>' means "at least this size", never shrink (would wreck the rootfs)
truncate -s ">$IMG_SIZE" "$WORK_IMG"
ok "work image is $(( $(stat -c%s "$WORK_IMG") / 1024 / 1024 )) MiB"

# --- [4] attach loop device ----------------------------------------------------
step "Attach loop device"
LOOP=""; MNT=""
cleanup() {
  set +e
  if [[ -n $MNT ]]; then
    for m in dev/pts dev proc sys var/cache/apt/archives; do
      mountpoint -q "$MNT/$m" && umount "$MNT/$m"
    done
    if [[ -e "$MNT/etc/resolv.conf.prep-bak" ]]; then
      rm -f "$MNT/etc/resolv.conf"
      mv "$MNT/etc/resolv.conf.prep-bak" "$MNT/etc/resolv.conf"
    fi
    mountpoint -q "$MNT/boot/firmware" && umount "$MNT/boot/firmware"
    mountpoint -q "$MNT" && umount "$MNT"
    [[ -d $MNT ]] && rmdir "$MNT"
  fi
  # The desktop's udisks2 auto-mounts p1/p2 in the file manager the moment the
  # partitioned loop device appears. Those mounts hold the device open, so a
  # plain `losetup -d` can only flag it for autoclear and it lingers in lsblk
  # across runs. Drop any outside mount of our partitions before detaching.
  if [[ -n $LOOP ]]; then
    for part in "${LOOP}p"*; do
      [[ -b $part ]] || continue
      while read -r mp; do
        [[ -n $mp ]] && umount "$mp" 2>/dev/null
      done < <(findmnt -rno TARGET -S "$part")
    done
    losetup -d "$LOOP" 2>/dev/null
  fi
}
trap cleanup EXIT

LOOP=$(losetup -P -f --show "$WORK_IMG")
udevadm settle
BOOT_DEV="${LOOP}p1"
ROOT_DEV="${LOOP}p2"
if [[ ! -b $ROOT_DEV ]]; then
  partprobe "$LOOP"; udevadm settle
fi
[[ -b $BOOT_DEV && -b $ROOT_DEV ]] || die "partitions did not appear under $LOOP"
ok "attached $LOOP ($BOOT_DEV boot, $ROOT_DEV root)"

# --- [5] grow root partition + filesystem to fill the image -------------------
step "Grow root filesystem to fill the image"
parted -s "$LOOP" resizepart 2 100%
partprobe "$LOOP"; udevadm settle
e2fsck -fy "$ROOT_DEV" || true
resize2fs "$ROOT_DEV"
ok "rootfs now $(( $(blockdev --getsize64 "$ROOT_DEV") / 1024 / 1024 )) MiB"

# --- [6] mount ----------------------------------------------------------------
step "Mount the image"
MNT=$(mktemp -d "${TMPDIR:-/tmp}/prep-sd.XXXXXX")
mount "$ROOT_DEV" "$MNT"
mount "$BOOT_DEV" "$MNT/boot/firmware"
ROOT=$MNT
BOOT=$MNT/boot/firmware
[[ -f "$BOOT/config.txt" && -d "$ROOT/etc" ]] || die "mounted image does not look like Raspberry Pi OS"
ok "mounted at $MNT (boot: $BOOT)"

# --- [7] boot partition: headless first boot --------------------------------
step "Boot partition: headless first boot"
touch "$BOOT/ssh"
info "SSH enabled"

# default creds (skip the first-boot user wizard)
printf 'pi:%s\n' "$(openssl passwd -6 raspberry)" > "$BOOT/userconf.txt"
info "user 'pi' / password 'raspberry' preseeded"

# USB gadget: put dwc2 into peripheral mode + load the module early. We do NOT
# load g_ether — the gadget is assembled at boot as CDC-NCM via configfs (see
# step 8). NB: stock config.txt already ships `dtoverlay=dwc2,dr_mode=host`
# under a [cm4]/[cm5] filter — that must NOT satisfy this check, or the Pi Zero
# never gets put into peripheral mode (no UDC). Match the peripheral override
# specifically, and append it under [all] at EOF so it wins for every model.
if ! grep -qE '^dtoverlay=dwc2,dr_mode=peripheral' "$BOOT/config.txt"; then
  printf '\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\n' >> "$BOOT/config.txt"
  info "added dtoverlay=dwc2,dr_mode=peripheral to config.txt"
fi
# cmdline.txt is a single line; load dwc2 early so the UDC exists by the time
# usb-gadget-ncm.service runs. (No g_ether / no g_ether.*_addr params.)
if ! grep -q 'modules-load=dwc2' "$BOOT/cmdline.txt"; then
  sed -i 's/\brootwait\b/rootwait modules-load=dwc2/' "$BOOT/cmdline.txt"
  info "added modules-load=dwc2 to cmdline.txt"
fi
ok "boot partition staged"

# --- [8] USB CDC-NCM gadget + static link ------------------------------------
step "USB CDC-NCM gadget (configfs) + static 10.42.0.1 before NetworkManager"
# Fixed gadget MACs: host side 9a:57:0e:12:34:56 (keeps the PC's NIC name
# stable), Pi side 9a:57:0e:12:34:57. NCM rather than the legacy g_ether ECM
# gadget: ECM's bulk TX path stalls against many xHCI hosts
# ("cdc_ether ... NETDEV WATCHDOG: transmit queue timed out").
install -d "$ROOT/usr/local/sbin"
cat > "$ROOT/usr/local/sbin/usb-gadget-ncm.sh" <<'EOF'
#!/bin/sh
# CDC-NCM USB Ethernet gadget for the Resistor-Reader appliance.
set -e
G=/sys/kernel/config/usb_gadget/rr0
HOST_MAC=9a:57:0e:12:34:56
DEV_MAC=9a:57:0e:12:34:57
IP=10.42.0.1/24

find_iface() {
  for d in /sys/class/net/*; do
    [ -f "$d/address" ] || continue
    [ "$(cat "$d/address" 2>/dev/null)" = "$DEV_MAC" ] && { basename "$d"; return 0; }
  done
  return 1
}

up() {
  modprobe configfs     2>/dev/null || true
  modprobe libcomposite 2>/dev/null || true
  modprobe usb_f_ncm    2>/dev/null || true
  mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config 2>/dev/null || true

  if [ ! -d "$G" ]; then
    i=0; while [ -z "$(ls /sys/class/udc 2>/dev/null)" ]; do
      i=$((i+1)); [ "$i" -gt 150 ] && { echo "no UDC after 15s"; exit 1; }; sleep 0.1
    done
    udc=$(ls /sys/class/udc | head -n1)

    mkdir -p "$G"
    echo 0x1d6b > "$G/idVendor"        # Linux Foundation
    echo 0x0104 > "$G/idProduct"       # Multifunction Composite Gadget
    echo 0x0100 > "$G/bcdDevice"
    echo 0x0200 > "$G/bcdUSB"
    echo 0xEF   > "$G/bDeviceClass"    # Misc (IAD)
    echo 0x02   > "$G/bDeviceSubClass"
    echo 0x01   > "$G/bDeviceProtocol"

    mkdir -p "$G/strings/0x409"
    echo "$(cat /etc/machine-id 2>/dev/null || echo rr0000000000)" > "$G/strings/0x409/serialnumber"
    echo "Raspberry Pi"               > "$G/strings/0x409/manufacturer"
    echo "Resistor-Reader USB gadget" > "$G/strings/0x409/product"

    mkdir -p "$G/functions/ncm.usb0"
    echo "$HOST_MAC" > "$G/functions/ncm.usb0/host_addr"
    echo "$DEV_MAC"  > "$G/functions/ncm.usb0/dev_addr"

    mkdir -p "$G/configs/c.1/strings/0x409"
    echo "CDC-NCM" > "$G/configs/c.1/strings/0x409/configuration"
    echo 250       > "$G/configs/c.1/MaxPower"
    ln -sf "$G/functions/ncm.usb0" "$G/configs/c.1/"

    echo "$udc" > "$G/UDC"
  fi

  i=0; while ! iface=$(find_iface); do
    i=$((i+1)); [ "$i" -gt 150 ] && { echo "gadget netdev never appeared"; exit 1; }; sleep 0.1
  done
  ip link set "$iface" up
  ip addr replace "$IP" dev "$iface"
  echo "gadget up: $iface -> $IP"
}

down() {
  [ -d "$G" ] || exit 0
  echo "" > "$G/UDC" 2>/dev/null || true
  rm -f "$G"/configs/c.1/ncm.usb0
  rmdir "$G"/configs/c.1/strings/0x409 "$G"/configs/c.1 \
        "$G"/functions/ncm.usb0 "$G"/strings/0x409 "$G" 2>/dev/null || true
}

case "${1:-up}" in
  up)   up ;;
  down) down ;;
  *) echo "usage: $0 {up|down}"; exit 1 ;;
esac
EOF
chmod +x "$ROOT/usr/local/sbin/usb-gadget-ncm.sh"

cat > "$ROOT/etc/systemd/system/usb-gadget-ncm.service" <<'EOF'
[Unit]
Description=USB CDC-NCM Ethernet gadget (static 10.42.0.1)
DefaultDependencies=no
After=systemd-modules-load.service sys-kernel-config.mount
Wants=sys-kernel-config.mount
Before=network-pre.target NetworkManager.service systemd-networkd.service
Wants=network-pre.target
Conflicts=shutdown.target
Before=shutdown.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/usb-gadget-ncm.sh up
ExecStop=/usr/local/sbin/usb-gadget-ncm.sh down

[Install]
WantedBy=sysinit.target
EOF
install -d "$ROOT/etc/systemd/system/sysinit.target.wants"
ln -sf ../usb-gadget-ncm.service "$ROOT/etc/systemd/system/sysinit.target.wants/usb-gadget-ncm.service"

# This image's networking is cloud-init + netplan -> NetworkManager, and NM's
# generated "globally-managed-devices" list does NOT include the gadget iface,
# so NM would ignore any keyfile anyway. Make that explicit + belt-and-braces:
# keep NM's hands off the gadget so it can't clobber the static address.
install -d "$ROOT/etc/NetworkManager/conf.d"
cat > "$ROOT/etc/NetworkManager/conf.d/99-usb-gadget-unmanaged.conf" <<'EOF'
[device-usb-gadget-ncm]
match-device=mac:9A:57:0E:12:34:57
managed=0
EOF
ok "usb-gadget-ncm.service + NM unmanaged rule written"

# --- [9] qemu-arm chroot: mount --------------------------------------------------
step "qemu-arm chroot: bind mounts + DNS"
mount --bind /dev      "$ROOT/dev"
mount --bind /dev/pts  "$ROOT/dev/pts"
mount -t proc  proc    "$ROOT/proc"
mount -t sysfs sysfs   "$ROOT/sys"

# persistent host-side apt archive cache (survives across runs; unmounted before
# the image is finalised so the downloaded .debs never bloat the flashed card)
mkdir -p "$APT_CACHE/partial"
mount --bind "$APT_CACHE" "$ROOT/var/cache/apt/archives"

# give the chroot working DNS (stash the image's original, symlink or file)
mv "$ROOT/etc/resolv.conf" "$ROOT/etc/resolv.conf.prep-bak"
cp -L /etc/resolv.conf "$ROOT/etc/resolv.conf"
ok "mounted; entering chroot"

# --- [10] chroot: apt upgrade + install + venv --------------------------------
step "chroot: apt upgrade, package install, venv build"
env BRANCH="$BRANCH" REPO="$REPO" APT_PKGS="${APT_PKGS[*]}" \
  chroot "$ROOT" /usr/bin/env -i \
    HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive \
    BRANCH="$BRANCH" REPO="$REPO" APT_PKGS="${APT_PKGS[*]}" \
    FULL_UPGRADE="$FULL_UPGRADE" KEEP_KERNELS="$KEEP_KERNELS" \
    BLUE="$BLUE" GREEN="$GREEN" RESET="$RESET" \
    /bin/bash -euo pipefail <<'CHROOT'
cstep() { printf '\n%s  ·· %s%s\n' "${BLUE:-}" "$*" "${RESET:-}"; }

# Everything below runs as emulated ARM under qemu-user (~5-10x slower than
# native, mostly single-threaded). The wins are in NOT doing redundant work:
# defer initramfs to a single run, skip man-db, skip fsync, deny service starts.
cat > /etc/dpkg/dpkg.cfg.d/99-prep-speed <<'EOF'
force-unsafe-io
path-exclude /usr/share/man/*
path-exclude /usr/share/doc/*
EOF
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d

divert()   { dpkg-divert --local --rename --add "$1" >/dev/null; ln -sf /bin/true "$1"; }
undivert() { rm -f "$1"; dpkg-divert --local --rename --remove "$1" >/dev/null; }
restore() {
  set +e
  undivert /usr/sbin/update-initramfs
  undivert /usr/bin/mandb
  rm -f /usr/sbin/policy-rc.d /etc/dpkg/dpkg.cfg.d/99-prep-speed
}
trap restore EXIT
divert /usr/sbin/update-initramfs
divert /usr/bin/mandb

cstep "apt-get update"
apt-get update
if [ "$FULL_UPGRADE" = 1 ]; then
  cstep "apt-get full-upgrade"
  apt-get -y full-upgrade
else
  cstep "skipping full-upgrade (FULL_UPGRADE=0)"
fi
cstep "apt-get install: $APT_PKGS"
apt-get -y --no-install-recommends install $APT_PKGS
# no `apt-get clean` — /var/cache/apt/archives is the host-side bind mount we
# want to keep; it is unmounted before the image is finalised anyway

# Raspberry Pi OS installs a kernel for every board flavour (v6 = Pi 1 / Zero,
# v7 = Pi 2/3 / Zero 2, v8 = Pi 3/4/5 64-bit) AND keeps the previously-installed
# build alongside the fresh one. Every surviving /boot/vmlinuz-* costs one ~50s
# initramfs build under qemu, so drop every kernel that isn't the newest build
# of a flavour named in KEEP_KERNELS. This must match the *versioned* packages
# (linux-image-6.18.39+rpt-rpi-v7), not just the linux-image-rpi-v7 metapackages.
cstep "prune kernels (keep: ${KEEP_KERNELS:-all flavours}, newest build only)"
kpkgs=$(dpkg-query -W -f='${Package}|${Status}\n' \
          'linux-image-*' 'linux-headers-*' 'linux-base-*' 2>/dev/null \
        | awk -F'|' '$2=="install ok installed"{print $1}')
newest=$(printf '%s\n' $kpkgs \
         | sed -n 's/^linux-image-\([0-9].*\)+rpt-rpi-v[0-9].*$/\1/p' \
         | sort -V | tail -n1)
echo "newest kernel build: ${newest:-unknown}"
purge=""
for pkg in $kpkgs; do
  flav=${pkg##*-}
  case "$pkg" in
    linux-image-rpi-v[0-9]*|linux-headers-rpi-v[0-9]*|linux-base-rpi-v[0-9]*)
      # per-flavour metapackage: keep only if the flavour is wanted
      case " ${KEEP_KERNELS:-$flav} " in *" $flav "*) : ;; *) purge="$purge $pkg" ;; esac ;;
    linux-image-[0-9]*-v[0-9]*|linux-headers-[0-9]*-v[0-9]*|linux-base-[0-9]*-v[0-9]*)
      # versioned per-flavour kernel: keep only wanted flavour AND newest build
      ver=${pkg#linux-*-}; ver=${ver%+rpt-rpi-*}
      keep=1
      case " ${KEEP_KERNELS:-$flav} " in *" $flav "*) : ;; *) keep=0 ;; esac
      [ -n "$newest" ] && [ "$ver" != "$newest" ] && keep=0
      [ "$keep" = 0 ] && purge="$purge $pkg" ;;
  esac
done
if [ -n "$purge" ]; then
  echo "purging:$purge"
  apt-get -y purge $purge || echo "kernel purge failed — continuing (extra initramfs builds)"
fi
cstep "apt-get autoremove --purge (drops now-orphaned kernel headers/base)"
apt-get -y --purge autoremove || true

# dpkg leaves the module/header trees behind ("directory not empty so not
# removed") for any flavour we purged. Drop them so the image isn't carrying
# ~tens of MB of kernel modules for boards it will never run on.
if [ -n "${KEEP_KERNELS:-}" ]; then
  for d in /usr/lib/modules/* /usr/src/linux-headers-*; do
    [ -e "$d" ] || continue
    case "${d##*-}" in
      v[0-9]*)
        case " $KEEP_KERNELS " in
          *" ${d##*-} "*) : ;;
          *) echo "rm stale kernel tree $d"; rm -rf "$d" ;;
        esac ;;
    esac
  done
fi

cstep "enable i2c"
raspi-config nonint do_i2c 0

cstep "clone $REPO @ $BRANCH"
if [ -d /home/pi/Resistor-Reader/.git ]; then
  echo "repo already present — fetching"
  cd /home/pi/Resistor-Reader
  sudo -u pi -H git remote set-url origin "$REPO"
  sudo -u pi -H git fetch origin
else
  rm -rf /home/pi/Resistor-Reader
  sudo -u pi -H git clone "$REPO" /home/pi/Resistor-Reader
  cd /home/pi/Resistor-Reader
fi
sudo -u pi -H git checkout "$BRANCH"
sudo -u pi -H git reset --hard "origin/$BRANCH"

cstep "build .venv + install adafruit-circuitpython-ht16k33"
sudo -u pi -H python3 -m venv .venv --system-site-packages
sudo -u pi -H .venv/bin/pip install --no-cache-dir adafruit-circuitpython-ht16k33

# config.yaml now ships appliance-safe (runtime.debug.enabled: false), so there
# is nothing to patch. Fail loudly if that ever regresses: with debug on, every
# button press writes five or six JPEGs into a Log2Ram RAM disk.
cstep "verify config.yaml ships with debug off"
if grep -qE '^\s+enabled:\s*true' config.yaml; then
  echo "ERROR: config.yaml has runtime.debug.enabled: true" >&2
  exit 1
fi

cstep "install resistor-reader.service"
install -m 0644 scripts/resistor-reader.service \
  /etc/systemd/system/resistor-reader.service
systemctl enable resistor-reader.service

cstep "restore diversions + regenerate initramfs (once per installed kernel)"
restore; trap - EXIT
for kimg in /boot/vmlinuz-*; do
  [ -e "$kimg" ] || continue                       # no kernels -> nothing to do
  kver=${kimg#/boot/vmlinuz-}
  echo "initramfs for $kver"
  update-initramfs -c -k "$kver" 2>/dev/null || update-initramfs -u -k "$kver"
done
CHROOT
ok "chroot work complete"

# --- [11] release ------------------------------------------------------------
step "Release the image"
cleanup            # drop mounts + loop device now, not at EXIT
trap - EXIT
LOOP=""; MNT=""
sync
ok "image staged and detached"

# --- [12] checksum ----------------------------------------------------------
step "Checksum"
info "sha256sum $(basename "$WORK_IMG") (a few seconds on NVMe)..."
SHA=$(sha256sum "$WORK_IMG" | cut -d' ' -f1)
printf '%s  %s\n' "$SHA" "$(basename "$WORK_IMG")" > "$WORK_IMG.sha256"
ok "$SHA"
info "written to $WORK_IMG.sha256  (cd there && sha256sum -c $(basename "$WORK_IMG").sha256)"

# --- [13] done -----------------------------------------------------------------
step "Done"
printf '%s' "$GREEN"
cat <<EOF
staged image ready:  $WORK_IMG  ($(( $(stat -c%s "$WORK_IMG") / 1024 / 1024 )) MiB)
sha256:              $SHA

flash it to the card (DOUBLE-CHECK the device — this wipes it):

    sudo dd if=$WORK_IMG of=/dev/sdX bs=4M conv=fsync status=progress

or use Raspberry Pi Imager → "Use custom image".

first boot auto-expands the rootfs to fill the card (stock Pi OS
init_resize hook). If "df -h /" still shows only a few GiB after
boot, run once:
    sudo raspi-config nonint do_expand_rootfs && sudo reboot

connecting from this PC: plug the Pi's data port in, give the gadget
NIC a static address on the same /24, then ssh:
    sudo nmcli connection add type ethernet con-name pi-gadget \
      mac 9a:57:0e:12:34:56 ipv4.method manual \
      ipv4.addresses 10.42.0.2/24 ipv6.method ignore
    ssh pi@10.42.0.1            # password: raspberry
(the Pi holds 10.42.0.1 via usb-gadget-ncm.service; there is no DHCP
 on the link. If ssh times out, on the Pi's card read
 /boot/firmware/netdebug.txt.)

Then, over USB (ssh pi@10.42.0.1), once you've confirmed it works,
make the root filesystem read-only with:

    sudo raspi-config nonint do_overlayfs 0 && sudo reboot

(doing it now, offline, risks an unbootable initramfs under qemu — it's a
 one-time ~2 min step on the Pi. To edit code later: same command with
 'do_overlayfs 1', reboot, git pull, then re-enable.)
EOF
printf '%s' "$RESET"
