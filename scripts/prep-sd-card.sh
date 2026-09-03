#!/usr/bin/env bash
#
# prep-sd-card.sh — stage a freshly-flashed Raspberry Pi OS card (32-bit / Trixie
# Lite) for the Resistor-Reader appliance on a Pi Zero, doing all the slow work
# (apt upgrade, package install, pip builds) here on a fast machine via a
# qemu-arm chroot instead of on the Pi's single core.
#
# Result:
#   * user "pi" / password "raspberry" (defaults), SSH enabled, no setup wizard
#   * USB OTG gadget ethernet: plug the Pi's data port into this PC, then
#     `ssh pi@10.42.0.1` (Pi runs DHCP/NAT for the host via NM ipv4 method=shared)
#   * all README apt packages + i2c-tools installed and fully upgraded
#   * Resistor-Reader cloned at /home/pi/Resistor-Reader on branch claude-rewrite
#   * .venv (system-site-packages) with adafruit-circuitpython-ht16k33
#   * i2c enabled; debug JPEG writes disabled in config.yaml
#   * read-only root: NOT enabled here (see note at end) — one command on the Pi
#
# Run as root with the card mounted. Adjust BOOT/ROOT to your mountpoints.
set -euo pipefail

BOOT=${BOOT:-/run/media/eric/bootfs}
ROOT=${ROOT:-/run/media/eric/rootfs}
BRANCH=${BRANCH:-claude-rewrite}
REPO=${REPO:-https://github.com/ericboehlke/Resistor-Reader.git}

APT_PKGS=(
  git build-essential
  python3-dev python3-pip
  python3-rpi.gpio python3-picamera2 python3-opencv
  python3-pil python3-scipy python3-yaml python3-pytest
  i2c-tools dnsmasq-base
)

[[ $EUID -eq 0 ]] || { echo "must run as root" >&2; exit 1; }
[[ -f "$BOOT/config.txt" && -d "$ROOT/etc" ]] || { echo "card not mounted at $BOOT / $ROOT" >&2; exit 1; }

# --- sanity: is this actually a good flash? -------------------------------------
if ! head -c1 "$BOOT/config.txt" | grep -q '[^[:space:][:cntrl:]]'; then
  echo "config.txt looks empty/NUL — bad flash, aborting" >&2; exit 1
fi

# --- boot partition: headless first boot --------------------------------------
touch "$BOOT/ssh"

# default creds (skip the first-boot user wizard)
printf 'pi:%s\n' "$(openssl passwd -6 raspberry)" > "$BOOT/userconf.txt"

# USB gadget ethernet
if ! grep -q '^dtoverlay=dwc2' "$BOOT/config.txt"; then
  printf '\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\n' >> "$BOOT/config.txt"
fi
# cmdline.txt is a single line; insert the module load right after rootwait,
# with fixed gadget MACs so the host NIC name is stable across reboots
if ! grep -q 'modules-load=dwc2' "$BOOT/cmdline.txt"; then
  sed -i 's/\brootwait\b/rootwait modules-load=dwc2,g_ether g_ether.host_addr=9a:57:0e:12:34:56 g_ether.dev_addr=9a:57:0e:12:34:57/' "$BOOT/cmdline.txt"
fi

# NetworkManager profile: Pi hands the host an address + NATs its uplink
install -d -m 700 "$ROOT/etc/NetworkManager/system-connections"
cat > "$ROOT/etc/NetworkManager/system-connections/usb0.nmconnection" <<'EOF'
[connection]
id=usb0
type=ethernet
interface-name=usb0
autoconnect=true

[ipv4]
method=shared

[ipv6]
method=ignore
EOF
chmod 600 "$ROOT/etc/NetworkManager/system-connections/usb0.nmconnection"

# --- qemu-arm chroot ----------------------------------------------------------
command -v qemu-arm-static >/dev/null || command -v qemu-arm >/dev/null || {
  echo "install qemu-user-static (+ binfmt) first" >&2; exit 1; }

cleanup() {
  for m in boot/firmware dev/pts dev proc sys; do
    mountpoint -q "$ROOT/$m" && umount "$ROOT/$m" || true
  done
  # restore the card's own resolv.conf
  rm -f "$ROOT/etc/resolv.conf"
  [[ -e "$ROOT/etc/resolv.conf.prep-bak" ]] && mv "$ROOT/etc/resolv.conf.prep-bak" "$ROOT/etc/resolv.conf" || true
}
trap cleanup EXIT

mount --bind /dev      "$ROOT/dev"
mount --bind /dev/pts  "$ROOT/dev/pts"
mount -t proc  proc    "$ROOT/proc"
mount -t sysfs sysfs   "$ROOT/sys"
mount --bind "$BOOT"   "$ROOT/boot/firmware"

# give the chroot working DNS (stash the card's original, symlink or file)
mv "$ROOT/etc/resolv.conf" "$ROOT/etc/resolv.conf.prep-bak"
cp -L /etc/resolv.conf "$ROOT/etc/resolv.conf"

env BRANCH="$BRANCH" REPO="$REPO" APT_PKGS="${APT_PKGS[*]}" \
  chroot "$ROOT" /usr/bin/env -i \
    HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive \
    BRANCH="$BRANCH" REPO="$REPO" APT_PKGS="${APT_PKGS[*]}" \
    /bin/bash -euo pipefail <<'CHROOT'
apt-get update
apt-get -y full-upgrade
apt-get -y install $APT_PKGS
apt-get clean

raspi-config nonint do_i2c 0

sudo -u pi -H git clone "$REPO" /home/pi/Resistor-Reader
cd /home/pi/Resistor-Reader
sudo -u pi -H git checkout "$BRANCH"
sudo -u pi -H python3 -m venv .venv --system-site-packages
sudo -u pi -H .venv/bin/pip install --no-cache-dir adafruit-circuitpython-ht16k33

# appliance: no debug image writes
sed -i -E 's/^( *)debug_image: true/\1debug_image: false/' config.yaml
sed -i -E 's/^( *)enabled: true/\1enabled: false/' config.yaml
CHROOT

echo
echo "card prepared. On the Pi's FIRST boot (over USB: ssh pi@10.42.0.1), once"
echo "you've confirmed it works, make the root filesystem read-only with:"
echo
echo "    sudo raspi-config nonint do_overlayfs 0 && sudo reboot"
echo
echo "(doing it now, offline, risks an unbootable initramfs under qemu — it's a"
echo " one-time ~2 min step on the Pi. To edit code later: same command with"
echo " 'do_overlayfs 1', reboot, git pull, then re-enable.)"
