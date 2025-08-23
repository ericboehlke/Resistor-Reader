# Resistor-Reader

A project to read the color code on resistors

## Development

This project uses [uv](https://github.com/astral-sh/uv) for dependency
management and [flit](https://flit.pypa.io) as the build backend.

Install the dependencies:

```bash
uv sync
```

Run the tests:

```bash
uv run pytest
```

Build a distribution:

```bash
uv build
```

## Install on Raspberry Pi Zero

1. Flash an SD card with Raspbian Lite (32 bit)
2. Connect the Pi to a USB to Ethernet adapter and connect it to the network
3. Log in to the Pi
4. `sudo apt update`
5. `sudo apt full-upgrade`
6. `sudo apt install git`
7. `git clone https://github.com/ericboehlke/Resistor-Reader.git`
8. `cd Resistor-Reader`
9. Install dependencies

```bash
sudo apt install \
  python3-dev \
  python3-pip \
  python3-rpi.gpio \
  python3-picamera2 \
  python3-opencv \
  python3-pil \
  python3-scipy \
  python3-yaml \
  python3-pytest
```

10. `python3 -m venv .venv --system-site-packages`
11. `source .venv/bin/activate`
12. `python3 -m pip install adafruit-circuitpython-ht16k33`
13. Enable i2c using `raspi-config`

## Running

```bash
python3 resistor_reader/main.py read
```
