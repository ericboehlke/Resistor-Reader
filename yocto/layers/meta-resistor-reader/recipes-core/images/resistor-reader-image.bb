SUMMARY = "Minimal image with resistor reader and USB SSH"

require recipes-core/images/core-image-minimal.bb

IMAGE_FEATURES += "ssh-server-openssh"

IMAGE_INSTALL += "resistor-reader usb-gadget"

IMAGE_FSTYPES += "rpi-sdimg"
