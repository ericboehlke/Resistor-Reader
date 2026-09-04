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
from picamera2 import Picamera2
from RPi import GPIO

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


def setup_gpio(config: Config):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(config.leds_pin, GPIO.OUT, initial=GPIO.LOW)


def setup_display():
    display = segments.Seg14x4(board.I2C())
    display.brightness = 0.5
    display.fill(0)
    return display


def setup_camera(config: Config):
    cam = Picamera2()
    config_obj = cam.create_still_configuration(main={"size": config.resolution})
    cam.configure(config_obj)

    # Start camera, then set manual WB (disable AWB, apply gains)
    cam.start()
    # small warmup
    time.sleep(0.1)
    cam.set_controls(
        {
            "AwbEnable": False,  # turn off auto white balance
            "ColourGains": config.awb_gains,  # apply manual gains
        }
    )
    return cam


def gather_mode(picam2, display, config: Config):
    """Gather mode:
    Prompt for resistance, take picture, save image and resistance in CSV.
    """
    display.print("GATH")
    ensure_paths(config)
    resistance = input("resistance: ").strip()
    try:
        float(resistance)
    except ValueError:
        print("Invalid resistance value, please enter a number.")
        return
    display.print(resistance_str(float(resistance)))
    filename = config.save_dir / f"{str(config.image_number).zfill(4)}.jpg"
    GPIO.output(config.leds_pin, True)
    time.sleep(0.1)
    picam2.capture_file(str(filename))
    time.sleep(0.1)
    GPIO.output(config.leds_pin, False)
    with open(config.csv_path, "a", newline="") as csvfile:
        writer = csv.writer(
            csvfile, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL
        )
        writer.writerow([str(config.image_number), resistance])
    print(f"Saved image {filename} with resistance {resistance}")
    config.image_number += 1


def camera_mode(picam2, display, config: Config):
    """Camera mode:
    Wait for button press, take picture, save with incrementing filename.
    """
    while (outfile := Path(f"camera_capture_{config.image_number}.jpg")).exists():
        config.image_number += 1
    display.print("PUSH")
    print("Ready: press the button to take a picture...")
    GPIO.wait_for_edge(config.button_pin, GPIO.FALLING)
    # Simple debounce
    time.sleep(0.03)
    if GPIO.input(config.button_pin) == GPIO.LOW:
        print("Taking picture with flash...")
        display.print("SNAP")
        GPIO.output(config.leds_pin, True)
        time.sleep(0.1)
        picam2.capture_file(str(outfile))
        time.sleep(0.1)
        GPIO.output(config.leds_pin, False)
        display.print("DONE")
        print(f"Saved to {outfile.resolve()}")
    # Wait for release so we don't immediately retrigger
    while GPIO.input(config.button_pin) == GPIO.LOW:
        time.sleep(0.01)


def read_mode(picam2, display, config: Config):
    """Read mode:
    Wait for button press, take a picture, run the pipeline, and show the
    resistance -- or the failing stage's error code -- on the display.
    """
    GPIO.wait_for_edge(config.button_pin, GPIO.FALLING)
    time.sleep(0.03)  # Simple debounce
    if GPIO.input(config.button_pin) == GPIO.LOW:
        print("Taking picture...")
        display.print("READ")
        GPIO.output(config.leds_pin, True)
        time.sleep(0.1)
        try:
            img_array = picam2.capture_array("main")
        except Exception as e:  # camera not ready, driver/I-O error
            GPIO.output(config.leds_pin, False)
            show_error(display, ErrorCodeEnum.E01, str(e))
            time.sleep(2)
            return
        time.sleep(0.1)
        GPIO.output(config.leds_pin, False)

        print("Processing image...")
        try:
            result = orchestrator.read_pipeline(img_array, config.pipeline_config)
        except Exception:  # a stage blew up instead of reporting failure
            traceback.print_exc()
            show_error(display, ErrorCodeEnum.E05, "pipeline crashed")
            time.sleep(2)
            return

        if result.failure is not None or result.resistance is None:
            show_error(display, result.failure or ErrorCodeEnum.E04, result.error_msg)
            time.sleep(2)
            return

        # A wrong reading is worse than no reading, so refuse a value the
        # decoder could not separate from its runner-up.
        if result.confidence < config.min_confidence:
            show_error(
                display,
                ErrorCodeEnum.E06,
                f"margin {result.confidence:.1f} < {config.min_confidence:.1f}",
            )
            time.sleep(2)
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
    while GPIO.input(config.button_pin) == GPIO.LOW:
        time.sleep(0.01)


def run_loop(mode_func, config: Config):
    config.image_number = config.start_number
    display = None
    picam2 = None
    try:
        display = setup_display()
        display.print("LOAD")
        setup_gpio(config)
        try:
            picam2 = setup_camera(config)
        except Exception as e:  # no camera attached, driver failure
            print(f"Camera initialization failed: {e}")
            show_error(display, ErrorCodeEnum.E01, str(e))
            time.sleep(3)
            raise
        while True:
            mode_func(picam2, display, config)
    except KeyboardInterrupt:
        pass
    finally:
        if picam2 is not None:
            try:
                picam2.stop()
                picam2.close()
            except Exception:
                pass
        GPIO.cleanup()
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
        pipeline_config=orchestrator.load_config(
            getattr(args, "pipeline_config_file", None)
        ),
    )


def main():
    args = build_parser().parse_args()
    run_loop(args.func, config_from_args(args))


if __name__ == "__main__":
    main()
