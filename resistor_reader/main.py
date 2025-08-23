#!/usr/bin/env python3

import argparse
import csv
import time
from dataclasses import dataclass
from pathlib import Path

import board
import RPi.GPIO as GPIO
from adafruit_ht16k33 import segments
from picamera2 import Picamera2

from resistor_reader import orchestrator


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
    """Format a resistance value as a string with appropriate units."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.2f}k"
    else:
        return f"{value:.2f}"


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
    Wait for button press, take picture, display image on screen.
    """
    GPIO.wait_for_edge(config.BUTTON_PIN, GPIO.FALLING)
    time.sleep(0.03)  # Simple debounce
    if GPIO.input(config.BUTTON_PIN) == GPIO.LOW:
        print("Taking picture...")
        display.print("READ")
        GPIO.output(config.LEDS_PIN, True)
        time.sleep(0.1)
        img_array = picam2.capture_array("main")
        time.sleep(0.1)
        GPIO.output(config.LEDS_PIN, False)
        print("Processing image...")
        try:
            pipeline_config = (
                orchestrator.load_config(config.PIPELINE_CONFIG_FILE)
                if config.PIPELINE_CONFIG_FILE
                else None
            )
            resistance = orchestrator.read_resistor(img_array, pipeline_config)
        except ValueError as e:
            print(f"Error reading resistor: {e}")
            display.print("Err")
            time.sleep(2)
            return
        print(f"Detected resistance: {resistance} ohms")
        display.print(resistance_str(resistance))
    # Wait for release so we don't immediately retrigger
    while GPIO.input(config.BUTTON_PIN) == GPIO.LOW:
        time.sleep(0.01)


def run_loop(mode_func, config: Config):
    config.image_number = config.START_NUMBER
    try:
        display = setup_display()
        display.print("LOAD")
        setup_gpio(config)
        picam2 = setup_camera(config)
        while True:
            mode_func(picam2, display, config)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            picam2.stop()
            picam2.close()
        except Exception:
            pass
        GPIO.cleanup()
        display.fill(0)


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
