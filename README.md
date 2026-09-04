# Resistor-Reader

Press a button, and a Raspberry Pi Zero photographs the 4-band resistor sitting
on its tray, decodes the colour code with OpenCV, and shows the resistance on a
14-segment display. Fixed LEDs keep the lighting consistent; a failure shows an
error code instead of a wrong answer.

Currently reads **121 of 128** sample images correctly (94.5%). Only tan-bodied
4-band resistors are in scope.

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the pipeline works
* [docs/WORKFLOW.md](docs/WORKFLOW.md) — how to develop and tune it
* [docs/CODE_REVIEW_TODO.md](docs/CODE_REVIEW_TODO.md) — what still needs doing
* [hardware/WIRING.md](hardware/WIRING.md) — enclosure, GPIO wiring, and fasteners

## Development

Uses [uv](https://github.com/astral-sh/uv) for dependencies and
[flit](https://flit.pypa.io) as the build backend. Needs Python 3.11+.

```bash
uv sync            # install
uv run pytest      # run the tests
uvx ruff check .   # lint
uv build           # build a distribution
```

The CV pipeline runs anywhere. `main.py` needs the Pi's hardware (GPIO,
picamera2, I2C display), so on a dev machine drive the pipeline directly:

```bash
uv run python -c "
import numpy, PIL.Image
from resistor_reader.orchestrator import read_pipeline, load_config
r = read_pipeline(numpy.asarray(PIL.Image.open('resistor_pictures/0000.jpg')),
                  load_config('config.yaml'))
print(r.resistance, [c.value for c in r.colors])"
```

## Modes

`main.py` has three:

* **read** — the real one. Waits for the button, captures, runs the pipeline,
  displays the resistance or an error code.
* **gather** — prompts for a known resistance, captures, and appends the image
  and its value to the CSV. This built the test set.
* **camera** — captures to a numbered file on each press. Nothing else.

## Install on a Raspberry Pi Zero

`scripts/prep-sd-card.sh` builds the whole image on a fast machine through a
qemu-arm chroot, so the Pi never has to run `apt` or compile anything. It
installs the packages, clones this repo, builds the venv, enables I2C, installs
the systemd unit, and sets up a CDC-NCM USB gadget so the Pi answers at
`10.42.0.1` over the USB cable.

```bash
sudo ./scripts/prep-sd-card.sh          # see the header for env vars
```

Flash the resulting image, boot it, and the reader starts automatically:

```bash
ssh pi@10.42.0.1
systemctl status resistor-reader
journalctl -u resistor-reader -f
```

To run it by hand, stop the service first:

```bash
sudo systemctl stop resistor-reader
cd ~/Resistor-Reader && .venv/bin/python -m resistor_reader.main read
```
