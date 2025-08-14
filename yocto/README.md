# Yocto Build Instructions

This directory contains the metadata needed to build a Raspberry Pi Zero image
with the `resistor_reader` application pre-installed and reachable over USB
networking.

## Prerequisites

* GNU/Linux host with required Yocto build dependencies
* `repo` tool from Google (`sudo apt install repo` on Debian/Ubuntu)

## Fetch Sources

```bash
mkdir yocto-build
cd yocto-build
repo init -u ../Resistor-Reader -m yocto/manifest.xml
repo sync
```

## Configure Build Environment

```bash
source poky/oe-init-build-env
bitbake-layers add-layer ../meta-openembedded/meta-python \
                   ../meta-raspberrypi \
                   ../meta-resistor-reader
```

Edit `conf/local.conf` and set:

```
MACHINE ?= "raspberrypi0"
IMAGE_FSTYPES += "rpi-sdimg"
```

## Build Image

```
bitbake resistor-reader-image
```

The resulting SD card image will be located in
`tmp/deploy/images/raspberrypi0/`.

## USB SSH

The image configures the Pi Zero as a USB Ethernet gadget with IP
`192.168.7.2` and starts an OpenSSH server, allowing the host machine to SSH to
`root@192.168.7.2` after boot.
