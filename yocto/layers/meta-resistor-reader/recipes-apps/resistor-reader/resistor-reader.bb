FILESEXTRAPATHS:prepend := "${THISDIR}/../../../../:"

SUMMARY = "Resistor reader Python application"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=4ba25ca7e8c331cd6f20520ec37ef503"

SRC_URI = "file://LICENSE \
           file://resistor_reader"

S = "${WORKDIR}"

inherit python3native

do_install() {
    install -d ${D}${PYTHON_SITEPACKAGES_DIR}/resistor_reader
    cp -r ${WORKDIR}/resistor_reader/* ${D}${PYTHON_SITEPACKAGES_DIR}/resistor_reader/
}

RDEPENDS:${PN} += "\
    python3-core \
    python3-numpy \
    python3-pillow \
    python3-pyyaml \
    python3-opencv \
    python3-scipy \
    python3-picamera \
    python3-rpi-gpio \
    python3-adafruit-circuitpython-led-backpack \
"
