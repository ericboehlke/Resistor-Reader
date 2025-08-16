#!/usr/bin/env python3
import csv
import os
from pathlib import Path
from time import sleep

import RPi.GPIO as GPIO
from picamera2 import Picamera2

# --- Config ---
LEDS_PIN = 27            # <-- set to your pin
SAVE_DIR = Path("resistors")
CSV_PATH = SAVE_DIR / "resistors.csv"
RESOLUTION = (640, 480)
AWB_GAINS = (1.5, 1.4)   # (red, blue) gains when AWB is disabled
START_NUMBER = 0         # <-- set your starting index
# ---------------

def ensure_paths():
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        # create header if you want one; otherwise omit this block
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.writer(f, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(["number", "resistance"])

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LEDS_PIN, GPIO.OUT, initial=GPIO.LOW)

def setup_camera():
    cam = Picamera2()
    # Still capture configuration at 640x480
    config = cam.create_still_configuration(main={"size": RESOLUTION})
    cam.configure(config)

    # Start camera, then set manual WB (disable AWB, apply gains)
    cam.start()
    # small warmup
    sleep(0.1)
    cam.set_controls({
        "AwbEnable": False,        # turn off auto white balance
        "ColourGains": AWB_GAINS,  # apply manual gains
    })
    return cam

def main():
    ensure_paths()
    setup_gpio()
    picam2 = setup_camera()

    number = START_NUMBER
    try:
        while True:
            resistance = input("resistance: ").strip()
            try:
                float(resistance)
            except ValueError:
                # any non-numeric input exits the loop (same as your original)
                break

            GPIO.output(LEDS_PIN, True)
            sleep(0.1)

            filename = SAVE_DIR / f"{str(number).zfill(4)}.jpg"
            picam2.capture_file(str(filename))

            sleep(0.1)
            GPIO.output(LEDS_PIN, False)

            with open(CSV_PATH, "a", newline="") as csvfile:
                writer = csv.writer(csvfile, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL)
                writer.writerow([str(number), resistance])

            number += 1

    finally:
        try:
            picam2.stop()
            picam2.close()
        except Exception:
            pass
        GPIO.cleanup()

if __name__ == "__main__":
    main()

