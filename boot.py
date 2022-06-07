import time
import board
import neopixel
import storage
from digitalio import DigitalInOut, Pull

print("hello from boot.py")  # see this in 'boot_out.txt'

led = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)

switch = DigitalInOut(board.A5)
switch.switch_to_input(Pull.UP)

if not switch.value:
    print("Pin A5 pulled down.Making CIRCUITPY writeable to Circuitpython")
    for i in range(5):  # blink LED
        led[0] = 0xffffff
        time.sleep(0.1)
        led[0] = 0x000000
        time.sleep(0.1)
    # storage.remount("/", readonly=False, disable_concurrent_write_protection=True)
    storage.remount("/", readonly=False)

else:
    print("Pin A5 not pulled down. Keeping Defaults")
