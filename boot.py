# circuitpython_disable_usb_boot.py
# Turn on/off certain USB features based on touching RX & TX pins
# Squeeze TX & RX pins with fingers to enable CIRCUITPY & REPL
# Otherwise, they are turned off
# CircuitPython 7.x only
# Rename this as "boot.py" in your CIRCUITPY drive on a QT PY
# @todbot 17 May 2021

import time
import board
import neopixel
import touchio
import storage

print("hello from boot.py")  # see this in 'boot_out.txt'

led = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
touch1in = touchio.TouchIn(board.D5)
touch2in = touchio.TouchIn(board.D6)

if touch1in.raw_value > 12000 and touch2in.raw_value > 12000:
    print("both RX & TX touched! Making CIRCUITPY writeable to Circuitpython")
    for i in range(5):  # blink LED
        led[0] = 0xffffff
        time.sleep(0.1)
        led[0] = 0x000000
        time.sleep(0.1)
    storage.remount("/", readonly=False)
    # or enable just certain HID devices
    #import usb_hid
    #usb_hid.enable(devices=(usb_hid.Device.MOUSE,))
    #usb_hid.enable(devices=(usb_hid.Device.KEYBOARD))
    #usb_hid.enable(devices=(usb_hid.Device.CONSUMER_CONTROL,))

else:
    print("RX & TX not touched. Keeping Defaults")
    # import storage
    # import usb_cdc
    # import usb_midi
    # storage.disable_usb_drive()  # disable CIRCUITPY
    # usb_cdc.disable()            # disable REPL
    # usb_midi.disable()           # disable MIDI
    #import usb_hid
    #usb_hid.disable()           # could also disable HID