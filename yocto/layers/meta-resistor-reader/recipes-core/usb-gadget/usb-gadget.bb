FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

SUMMARY = "USB gadget network setup for Pi Zero"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=4ba25ca7e8c331cd6f20520ec37ef503"

SRC_URI = "file://usb-gadget.sh \
           file://usb-gadget.service \
           file://LICENSE"

S = "${WORKDIR}"

inherit systemd

SYSTEMD_SERVICE:${PN} = "usb-gadget.service"

do_install() {
    install -d ${D}${sbindir}
    install -m 0755 ${WORKDIR}/usb-gadget.sh ${D}${sbindir}/usb-gadget.sh

    install -d ${D}${systemd_system_unitdir}
    install -m 0644 ${WORKDIR}/usb-gadget.service ${D}${systemd_system_unitdir}/usb-gadget.service
}
