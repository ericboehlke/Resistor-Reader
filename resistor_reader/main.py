#!/usr/bin/env python3

import argparse
import csv
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import board
import RPi.GPIO as GPIO
from adafruit_ht16k33 import segments
from picamera2 import Picamera2

from resistor_reader import orchestrator
from resistor_reader.models import ErrorCodeEnum


@dataclass
class Config:
    BUTTON_PIN: int
    LEDS_PIN: int
    SAVE_DIR: Path
    CSV_PATH: Path
    RESOLUTION: tuple
    AWB_GAINS: tuple
    START_NUMBER: int
    PIPELINE_CONFIG_FILE: str | None = None
    image_number: int = 0


def ensure_paths(config: Config):
    config.SAVE_DIR.mkdir(parents=True, exist_ok=True)
    if not config.CSV_PATH.exists():
        # create header if you want one; otherwise omit this block
        with open(config.CSV_PATH, "a", newline="") as f:
            writer = csv.writer(
                f, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL
            )
            writer.writerow(["number", "resistance"])


def setup_gpio(config: Config):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(config.LEDS_PIN, GPIO.OUT, initial=GPIO.LOW)


def setup_display():
    display = segments.Seg14x4(board.I2C())
    display.brightness = 0.5
    display.fill(0)
    return display


def setup_camera(config: Config):
    cam = Picamera2()
    # Still capture configuration at 640x480
    config_obj = cam.create_still_configuration(main={"size": config.RESOLUTION})
    cam.configure(config_obj)

    # Start camera, then set manual WB (disable AWB, apply gains)
    cam.start()
    # small warmup
    time.sleep(0.1)
    cam.set_controls(
        {
            "AwbEnable": False,  # turn off auto white balance
            "ColourGains": config.AWB_GAINS,  # apply manual gains
        }
    )
    return cam


def resistance_str(value):
    """Format a resistance value to fit the 4-character display.

    Keeps three significant figures at most so values like 10 kOhm render as
    ``10.0k`` rather than overflowing the four digits.
    """
    if value >= 1_000_000:
        scaled, suffix = value / 1_000_000, "M"
    elif value >= 1_000:
        scaled, suffix = value / 1_000, "k"
    else:
        scaled, suffix = float(value), ""
    if scaled >= 100:
        body = f"{scaled:.0f}"
    elif scaled >= 10:
        body = f"{scaled:.1f}"
    else:
        body = f"{scaled:.2f}"
    return f"{body}{suffix}"


def show_message(display, text: str) -> None:
    """Write to the segment display without ever taking the loop down with it."""
    try:
        display.print(text)
    except Exception:
        try:
            display.fill(0)
            display.print(text[:4])
        except Exception:
            pass


def show_error(display, code: ErrorCodeEnum, detail: str = "") -> None:
    """Report a failure on the console and surface its code on the display."""
    reason = f"{code.value}: {detail}" if detail else code.value
    print(f"[{code.name}] {reason}")
    show_message(display, code.name)


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
    filename = config.SAVE_DIR / f"{str(config.image_number).zfill(4)}.jpg"
    GPIO.output(config.LEDS_PIN, True)
    time.sleep(0.1)
    picam2.capture_file(str(filename))
    time.sleep(0.1)
    GPIO.output(config.LEDS_PIN, False)
    with open(config.CSV_PATH, "a", newline="") as csvfile:
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
    GPIO.wait_for_edge(config.BUTTON_PIN, GPIO.FALLING)
    # Simple debounce
    time.sleep(0.03)
    if GPIO.input(config.BUTTON_PIN) == GPIO.LOW:
        print("Taking picture with flash...")
        display.print("SNAP")
        GPIO.output(config.LEDS_PIN, True)
        time.sleep(0.1)
        picam2.capture_file(str(outfile))
        time.sleep(0.1)
        GPIO.output(config.LEDS_PIN, False)
        display.print("DONE")
        print(f"Saved to {outfile.resolve()}")
    # Wait for release so we don't immediately retrigger
    while GPIO.input(config.BUTTON_PIN) == GPIO.LOW:
        time.sleep(0.01)


def read_mode(picam2, display, config: Config):
    """Read mode:
    Wait for button press, take a picture, run the pipeline, and show the
    resistance -- or the failing stage's error code -- on the display.
    """
    GPIO.wait_for_edge(config.BUTTON_PIN, GPIO.FALLING)
    time.sleep(0.03)  # Simple debounce
    if GPIO.input(config.BUTTON_PIN) == GPIO.LOW:
        print("Taking picture...")
        display.print("READ")
        GPIO.output(config.LEDS_PIN, True)
        time.sleep(0.1)
        try:
            img_array = picam2.capture_array("main")
        except Exception as e:  # camera not ready, driver/I-O error
            GPIO.output(config.LEDS_PIN, False)
            show_error(display, ErrorCodeEnum.E01, str(e))
            time.sleep(2)
            return
        time.sleep(0.1)
        GPIO.output(config.LEDS_PIN, False)

        print("Processing image...")
        pipeline_config = orchestrator.load_config(
            config.PIPELINE_CONFIG_FILE or None
        )
        try:
            result = orchestrator.read_pipeline(img_array, pipeline_config)
        except Exception:  # a stage blew up instead of reporting failure
            traceback.print_exc()
            show_error(display, ErrorCodeEnum.E02, "pipeline crashed")
            time.sleep(2)
            return

        if result.failure is not None or result.resistance is None:
            show_error(
                display,
                result.failure or ErrorCodeEnum.E04,
                result.error_msg,
            )
            time.sleep(2)
            return

        colors = (
            ", ".join(c.value for c in result.colors) if result.colors else "?"
        )
        print(f"Detected resistance: {result.resistance:g} ohms [{colors}]")
        show_message(display, resistance_str(result.resistance))
    # Wait for release so we don't immediately retrigger
    while GPIO.input(config.BUTTON_PIN) == GPIO.LOW:
        time.sleep(0.01)


def run_loop(mode_func, config: Config):
    config.image_number = config.START_NUMBER
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


def main():
    parser = argparse.ArgumentParser(description="Resistor Reader")
    subparsers = parser.add_subparsers(
        dest="mode", required=True, help="Operation mode"
    )

    # Shared config arguments
    def add_common_args(sp):
        sp.add_argument(
            "--button-pin",
            type=int,
            default=17,
            help="GPIO pin for button",
        )
        sp.add_argument(
            "--leds-pin",
            type=int,
            default=27,
            help="GPIO pin for LEDs",
        )
        sp.add_argument(
            "--resolution",
            type=str,
            default="640x480",
            help="Camera resolution, e.g. 640x480",
        )
        sp.add_argument(
            "--awb-gains",
            type=str,
            default="1.5,1.4",
            help='AWB gains as "red,blue"',
        )

    # Gather subcommand
    parser_gather = subparsers.add_parser("gather", help="Gather mode")
    add_common_args(parser_gather)
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
        "--start-number",
        type=int,
        default=0,
        help="Starting image number",
    )

    # Camera subcommand
    parser_camera = subparsers.add_parser("camera", help="Camera mode")
    add_common_args(parser_camera)
    parser_camera.add_argument(
        "--start-number",
        type=int,
        default=0,
        help="Starting image number",
    )

    # Read subcommand
    parser_read = subparsers.add_parser("read", help="Read mode")
    add_common_args(parser_read)
    parser_read.add_argument(
        "--pipeline-config-file",
        type=str,
        default="config.yaml",
        help="Config file for the image processing pipeline.",
    )

    args = parser.parse_args()

    # Build config dataclass
    if hasattr(args, "save_dir"):
        save_dir = Path(args.save_dir)
    else:
        save_dir = Path("resistor_pictures")
    if hasattr(args, "csv_path") and args.csv_path is not None:
        csv_path = Path(args.csv_path)
    else:
        csv_path = save_dir / "resistors.csv"
    if "x" in args.resolution:
        w, h = args.resolution.lower().split("x")
        resolution = (int(w), int(h))
    else:
        raise ValueError("Resolution must be in the format WxH, e.g. 640x480")
    if "," in args.awb_gains:
        r, b = args.awb_gains.split(",")
        awb_gains = (float(r), float(b))
    else:
        raise ValueError("AWB gains must be in the format red,blue, e.g. 1.5,1.4")
    if hasattr(args, "start_number"):
        start_number = args.start_number
    else:
        start_number = 0
    if hasattr(args, "pipeline_config_file"):
        pipeline_config_file = args.pipeline_config_file
    else:
        pipeline_config_file = None

    config = Config(
        BUTTON_PIN=args.button_pin,
        LEDS_PIN=args.leds_pin,
        SAVE_DIR=save_dir,
        CSV_PATH=csv_path,
        RESOLUTION=resolution,
        AWB_GAINS=awb_gains,
        START_NUMBER=start_number,
        PIPELINE_CONFIG_FILE=pipeline_config_file,
    )

    if args.mode == "gather":
        run_loop(gather_mode, config)
    elif args.mode == "camera":
        run_loop(camera_mode, config)
    elif args.mode == "read":
        run_loop(read_mode, config)


if __name__ == "__main__":
    main()
