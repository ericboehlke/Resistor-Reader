#!/usr/bin/env python3
import time
from time import sleep
from pathlib import Path

import RPi.GPIO as GPIO
from picamera2 import Picamera2
import board
from adafruit_ht16k33 import segments

# --- Pins & config ---
BUTTON_PIN = 17          # Button to GND, using internal pull-up
LEDS_PIN = 27            # Flash/LED output pin
RESOLUTION = (640, 480)  # Image size
AWB_GAINS = (1.5, 1.4)   # Manual white balance gains (red, blue)
OUTFILE = Path("test.jpg")
DISPLAY_BRIGHTNESS = 0.5

# --- Helpers for display text (4 chars) ---
def show(display, text):
    s = (text or "")[:4].ljust(4)
    for i, ch in enumerate(s):
        display[i] = ch

def main():
    # --- Display setup ---
    display = segments.Seg14x4(board.I2C())
    display.brightness = DISPLAY_BRIGHTNESS
    display.fill(0)
    show(display, "BOOT")

    # --- GPIO setup ---
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(LEDS_PIN, GPIO.OUT, initial=GPIO.LOW)

    # --- Camera setup ---
    picam2 = Picamera2()
    config = picam2.create_still_configuration(main={"size": RESOLUTION})
    picam2.configure(config)
    picam2.start()
    sleep(0.2)  # warmup
    picam2.set_controls({
        "AwbEnable": False,
        "ColourGains": AWB_GAINS,
    })

    show(display, "PUSH")
    print("Ready: press the button to take a picture...")

    try:
        while True:
            # Wait for press (active-low)
            GPIO.wait_for_edge(BUTTON_PIN, GPIO.FALLING)
            # Simple debounce
            time.sleep(0.03)
            if GPIO.input(BUTTON_PIN) == GPIO.LOW:
                show(display, "SNAP")
                print("Button pressed: taking picture...")

                # Flash on, brief settle
                GPIO.output(LEDS_PIN, True)
                sleep(0.1)

                # Capture
                picam2.capture_file(str(OUTFILE))

                # Flash off
                GPIO.output(LEDS_PIN, False)

                show(display, "DONE")
                print(f"Saved to {OUTFILE.resolve()}")
                sleep(1.0)
                show(display, "PUSH")

            # Wait for release so we don't immediately retrigger
            while GPIO.input(BUTTON_PIN) == GPIO.LOW:
                time.sleep(0.01)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            picam2.stop()
            picam2.close()
        except Exception:
            pass
        display.fill(0)
        GPIO.cleanup()

if __name__ == "__main__":
    main()

