#!/bin/sh
set -e

modprobe libcomposite
G=/sys/kernel/config/usb_gadget/pi_gadget
mkdir -p $G
cd $G
echo 0x1d6b > idVendor
echo 0x0104 > idProduct
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB
mkdir -p strings/0x409
echo "fedcba9876543210" > strings/0x409/serialnumber
echo "ResistorReader" > strings/0x409/manufacturer
echo "ResistorReader" > strings/0x409/product
mkdir -p configs/c.1/strings/0x409
echo "Config 1" > configs/c.1/strings/0x409/configuration
echo 120 > configs/c.1/MaxPower
mkdir -p functions/ecm.usb0
ln -s functions/ecm.usb0 configs/c.1/
ls /sys/class/udc > UDC
ip addr add 192.168.7.2/24 dev usb0 || true
ip link set usb0 up || true
