"""Appliance entry point: button, camera, pipeline, segment display."""

from __future__ import annotations

import argparse
import csv
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import board
from adafruit_ht16k33 import segments
from gpiozero import LED, Button
from picamera2 import Picamera2

from resistor_reader import orchestrator
from resistor_reader.display import resistance_str, show_error, show_message
from resistor_reader.models import ErrorCodeEnum


@dataclass
class Config:
    button_pin: int
    leds_pin: int
    resolution: tuple[int, int]
    awb_gains: tuple[float, float]
    save_dir: Path = Path("resistor_pictures")
    csv_path: Path = Path("resistor_pictures/resistors.csv")
    start_number: int = 0
    # Fixed exposure for the (unchanging) tray lighting. ``None`` means measure
    # it once at startup; see ``setup_camera``.
    exposure_time: int | None = None
    analogue_gain: float = 1.0
    # Loaded once at startup rather than re-read from disk on every capture.
    pipeline_config: dict[str, Any] = field(default_factory=dict)
    image_number: int = 0

    @property
    def min_confidence(self) -> float:
        """Score margin below which a reading is refused as ``E06``.

        Zero (the default) accepts every reading the decoder considers legal.
        """
        decode_cfg = self.pipeline_config.get("decode", {}) or {}
        return float(decode_cfg.get("min_confidence", 0.0))


def ensure_paths(config: Config):
    config.save_dir.mkdir(parents=True, exist_ok=True)
    if not config.csv_path.exists():
        with open(config.csv_path, "a", newline="") as f:
            writer = csv.writer(
                f, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL
            )
            writer.writerow(["number", "resistance"])


def setup_gpio(config: Config) -> tuple[Button, LED]:
    # The switch ties the GPIO pin to 3.3V (not GND) when pressed -- see
    # hardware/WIRING.md -- so pull_up=False: gpiozero enables the internal
    # pull-down and reports the button pressed when the pin reads HIGH.
    # gpiozero picks the lgpio backend on this Pi (RPi.GPIO's edge detection
    # is broken on its kernel -- see wait_for_press's old docstring in git
    # history -- but lgpio talks to the modern gpiochip interface directly,
    # so edge waits work).
    button = Button(config.button_pin, pull_up=False, bounce_time=0.03)
    leds = LED(config.leds_pin)
    return button, leds


def setup_display():
    display = segments.Seg14x4(board.I2C())
    display.brightness = 0.5
    display.fill(0)
    return display


def _converge_exposure(
    cam, *, min_frames: int = 4, max_frames: int = 40, tol: float = 0.03
):
    """Step through frames until auto-exposure settles, and return the
    ``(ExposureTime microseconds, AnalogueGain)`` to lock in.

    With the LEDs on and steady, the AEC/AGC parks within a couple of frames
    and stays put; the hunting only happens when it meters a dark frame after
    the LEDs switch off between reads, which is exactly what locking prevents.
    ``capture_metadata`` blocks for the next frame, so the loop advances one
    frame per iteration.
    """
    prev = None
    exposure = gain = None
    for i in range(max_frames):
        metadata = cam.capture_metadata()
        exposure = metadata.get("ExposureTime")
        gain = metadata.get("AnalogueGain")
        if exposure is None or gain is None:
            break
        if i + 1 >= min_frames and prev and abs(exposure - prev) <= tol * prev:
            break
        prev = exposure
    if not exposure or not gain:
        raise RuntimeError("camera gave no exposure metadata to calibrate from")
    return int(exposure), float(gain)


def setup_camera(config: Config, leds: LED):
    cam = Picamera2()
    config_obj = cam.create_still_configuration(main={"size": config.resolution})
    cam.configure(config_obj)
    cam.start()

    # Manual white balance: the tray lighting is fixed, so a hunting AWB only
    # adds colour drift between reads.
    cam.set_controls({"AwbEnable": False, "ColourGains": config.awb_gains})

    # Lock exposure too. Left on auto, the AGC hunts to its ceiling after the
    # first frame and blows every later capture out -- red reads as orange,
    # brown as gold, or the resistor is lost against the background. The
    # lighting never changes, so one measurement under the LEDs holds for the
    # whole session.
    if config.exposure_time is not None:
        exposure, gain = config.exposure_time, config.analogue_gain
    else:
        leds.on()
        try:
            exposure, gain = _converge_exposure(cam)
        finally:
            leds.off()
        print(f"Calibrated exposure: {exposure} us at gain {gain:.2f}")
    cam.set_controls(
        {"AeEnable": False, "ExposureTime": exposure, "AnalogueGain": gain}
    )
    return cam


def gather_mode(picam2, display, config: Config, button: Button, leds: LED):
    """Gather mode:
    Prompt for resistance, take picture, save image and resistance in CSV.
    """
    show_message(display, "GATH")
    ensure_paths(config)
    resistance = input("resistance: ").strip()
    try:
        float(resistance)
    except ValueError:
        print("Invalid resistance value, please enter a number.")
        return
    show_message(display, resistance_str(float(resistance)))
    filename = config.save_dir / f"{str(config.image_number).zfill(4)}.jpg"
    leds.on()
    time.sleep(0.1)
    picam2.capture_file(str(filename))
    time.sleep(0.1)
    leds.off()
    with open(config.csv_path, "a", newline="") as csvfile:
        writer = csv.writer(
            csvfile, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL
        )
        writer.writerow([str(config.image_number), resistance])
    print(f"Saved image {filename} with resistance {resistance}")
    config.image_number += 1


def camera_mode(picam2, display, config: Config, button: Button, leds: LED):
    """Camera mode:
    Wait for button press, take picture, save with incrementing filename.
    """
    while (outfile := Path(f"camera_capture_{config.image_number}.jpg")).exists():
        config.image_number += 1
    show_message(display, "PUSH")
    print("Ready: press the button to take a picture...")
    button.wait_for_press()
    print("Taking picture with flash...")
    show_message(display, "SNAP")
    leds.on()
    time.sleep(0.1)
    picam2.capture_file(str(outfile))
    time.sleep(0.1)
    leds.off()
    show_message(display, "DONE")
    print(f"Saved to {outfile.resolve()}")
    # Wait for release so we don't immediately retrigger
    button.wait_for_release()


def read_mode(picam2, display, config: Config, button: Button, leds: LED):
    """Read mode:
    Wait for button press, take a picture, run the pipeline, and show the
    resistance -- or the failing stage's error code -- on the display.
    """
    button.wait_for_press()
    print("Taking picture...")
    show_message(display, "READ")
    leds.on()
    time.sleep(0.1)
    try:
        img_array = picam2.capture_array("main")
    except Exception as e:  # camera not ready, driver/I-O error
        leds.off()
        show_error(display, ErrorCodeEnum.E01, str(e))
        time.sleep(2)
        button.wait_for_release()
        return
    time.sleep(0.1)
    leds.off()

    print("Processing image...")
    try:
        result = orchestrator.read_pipeline(img_array, config.pipeline_config)
    except Exception:  # a stage blew up instead of reporting failure
        traceback.print_exc()
        show_error(display, ErrorCodeEnum.E05, "pipeline crashed")
        time.sleep(2)
        button.wait_for_release()
        return

    if result.failure is not None or result.resistance is None:
        show_error(display, result.failure or ErrorCodeEnum.E04, result.error_msg)
        time.sleep(2)
        button.wait_for_release()
        return

    # A wrong reading is worse than no reading, so refuse a value the
    # decoder could not separate from its runner-up.
    if not orchestrator.is_confident(result, config.min_confidence):
        show_error(
            display,
            ErrorCodeEnum.E06,
            f"margin {result.confidence:.1f} < {config.min_confidence:.1f}",
        )
        time.sleep(2)
        button.wait_for_release()
        return

    colors = ", ".join(c.value for c in result.colors) if result.colors else "?"
    timings = result._metadata.get("timings_ms", {})
    total_ms = sum(timings.values())
    print(
        f"Detected resistance: {result.resistance:g} ohms [{colors}] "
        f"in {total_ms:.0f} ms (confidence {result.confidence:.1f})"
    )
    show_message(display, resistance_str(result.resistance))
    # Wait for release so we don't immediately retrigger
    button.wait_for_release()


def run_loop(mode_func, config: Config):
    config.image_number = config.start_number
    display = None
    picam2 = None
    button = None
    leds = None
    try:
        display = setup_display()
        show_message(display, "LOAD")
        button, leds = setup_gpio(config)
        try:
            picam2 = setup_camera(config, leds)
        except Exception as e:  # no camera attached, driver failure
            print(f"Camera initialization failed: {e}")
            show_error(display, ErrorCodeEnum.E01, str(e))
            time.sleep(3)
            raise
        while True:
            mode_func(picam2, display, config, button, leds)
    except KeyboardInterrupt:
        pass
    finally:
        if picam2 is not None:
            try:
                picam2.stop()
                picam2.close()
            except Exception:
                pass
        if button is not None:
            button.close()
        if leds is not None:
            leds.close()
        if display is not None:
            try:
                display.fill(0)
            except Exception:
                pass


def parse_resolution(text: str) -> tuple[int, int]:
    if "x" not in text.lower():
        raise ValueError("Resolution must be in the format WxH, e.g. 640x480")
    w, h = text.lower().split("x", 1)
    return int(w), int(h)


def parse_awb_gains(text: str) -> tuple[float, float]:
    if "," not in text:
        raise ValueError("AWB gains must be in the format red,blue, e.g. 1.5,1.4")
    r, b = text.split(",", 1)
    return float(r), float(b)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resistor Reader")
    subparsers = parser.add_subparsers(dest="mode", required=True, help="Operation mode")

    def add_common_args(sp):
        sp.add_argument("--button-pin", type=int, default=17, help="GPIO pin for button")
        sp.add_argument("--leds-pin", type=int, default=27, help="GPIO pin for LEDs")
        sp.add_argument(
            "--resolution",
            type=str,
            default="640x480",
            help="Camera resolution, e.g. 640x480",
        )
        sp.add_argument(
            "--awb-gains", type=str, default="1.5,1.4", help='AWB gains as "red,blue"'
        )
        sp.add_argument(
            "--exposure-time",
            type=int,
            default=None,
            help="Lock exposure to N microseconds (default: measure it at startup)",
        )
        sp.add_argument(
            "--analogue-gain",
            type=float,
            default=1.0,
            help="Analogue gain to pair with --exposure-time",
        )

    parser_gather = subparsers.add_parser("gather", help="Gather mode")
    add_common_args(parser_gather)
    parser_gather.set_defaults(func=gather_mode)
    parser_gather.add_argument(
        "--csv-path",
        type=str,
        default=None,
        help="Path to CSV file (default: <save-dir>/resistors.csv)",
    )
    parser_gather.add_argument(
        "--save-dir",
        type=str,
        default="resistor_pictures",
        help="Directory to save images and CSV",
    )
    parser_gather.add_argument(
        "--start-number", type=int, default=0, help="Starting image number"
    )

    parser_camera = subparsers.add_parser("camera", help="Camera mode")
    add_common_args(parser_camera)
    parser_camera.set_defaults(func=camera_mode)
    parser_camera.add_argument(
        "--start-number", type=int, default=0, help="Starting image number"
    )

    parser_read = subparsers.add_parser("read", help="Read mode")
    add_common_args(parser_read)
    parser_read.set_defaults(func=read_mode)
    parser_read.add_argument(
        "--pipeline-config-file",
        type=str,
        default="config.yaml",
        help="Config file for the image processing pipeline.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> Config:
    save_dir = Path(getattr(args, "save_dir", "resistor_pictures"))
    csv_path = getattr(args, "csv_path", None)
    return Config(
        button_pin=args.button_pin,
        leds_pin=args.leds_pin,
        resolution=parse_resolution(args.resolution),
        awb_gains=parse_awb_gains(args.awb_gains),
        save_dir=save_dir,
        csv_path=Path(csv_path) if csv_path else save_dir / "resistors.csv",
        start_number=getattr(args, "start_number", 0),
        exposure_time=args.exposure_time,
        analogue_gain=args.analogue_gain,
        pipeline_config=orchestrator.load_config(
            getattr(args, "pipeline_config_file", None)
        ),
    )


def main():
    args = build_parser().parse_args()
    run_loop(args.func, config_from_args(args))


if __name__ == "__main__":
    main()
