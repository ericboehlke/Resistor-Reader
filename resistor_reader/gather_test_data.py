import csv
import picamera
import picamera.array
from time import sleep
import RPi.GPIO as GPIO
from Adafruit_LED_Backpack import AlphaNum4

BUTTON_PIN = 17
LEDS_PIN = 27
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN)
GPIO.setup(LEDS_PIN, GPIO.OUT)

number = 93

print("type the resistance and press 'enter' to take a picture")
print("enter a non-number to exit")

with picamera.PiCamera() as camera:
    camera.resolution = (640, 480)
    camera.awb_mode = "off"
    camera.awb_gains = (1.5, 1.4)
    sleep(0.1)
    try:
        while True:
            resistance = input("resistance: ")
            try:
                float(resistance)
            except ValueError:
                break
            GPIO.output(LEDS_PIN, True)
            sleep(0.1)
            camera.capture("resistors/" + str(number).zfill(4) + ".jpg")
            sleep(0.1)
            GPIO.output(LEDS_PIN, False)
            with open("resistors/resistors.csv", "a") as csvfile:
                writer = csv.writer(
                    csvfile, delimiter=",", quotechar="|", quoting=csv.QUOTE_MINIMAL
                )
                writer.writerow([str(number), resistance])
            number += 1
    finally:
        GPIO.cleanup()
