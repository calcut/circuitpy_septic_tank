from adafruit_motorkit import MotorKit

from circuitpy_mcu.mcu import Mcu

import time
import busio
import board

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback


# global variable so valves can be shut down after keyboard interrupt
valves = []
NUM_VALVES = 1


def main():

    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x68' : 'Realtime Clock PCF8523', # On Adalogger Featherwing
        '0x78' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4 and A3
        '0x72' : 'Sparkfun LCD Display',
        '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    mcu = Mcu(watchdog_timeout=20)

    try:
        global valves
        valve_driver = MotorKit(i2c=mcu.i2c, address=0x78)
        valves = [valve_driver.motor1, valve_driver.motor2, valve_driver.motor3, valve_driver.motor4]

        # Drop any unused valves as defined by the NUM_VALVES parameter
        valves = valves[:NUM_VALVES]
        
    except Exception as e:
        mcu.log_exception(e)
        mcu.log.warning('valve driver not found')

    def usb_serial_parser(string):
        global valves

        if string.startswith('v'):
            settings = string[1:].split()
            try:
                index = int(settings[0])
                speed = float(settings[1])
                valves[index].throttle = speed
                mcu.log.info(f'setting Valve {index} to speed {speed}')
            except Exception as e:
                print(e)
                mcu.log.warning(f'string {string} not valid for valve settings\n'
                                 +'input valve settings in format "v valve_number speed duration" e.g. p ')


    while True:
        mcu.watchdog.feed()
        mcu.read_serial(send_to=usb_serial_parser)

        
        

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for v in valves:
            v.throttle = 0
        # May want to add code to stop gracefully here 
        # e.g. turn off relays or valves
        
    except WatchDogTimeout:
        print('Code Stopped by WatchDog Timeout!')
        # supervisor.reload()
        # NB, sometimes soft reset is not enough! need to do hard reset here
        print('Performing hard reset in 15s')
        time.sleep(15)
        microcontroller.reset()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        print(traceback.format_exception(None, e, e.__traceback__))
        # Can we log here?
        print('Performing a hard reset in 15s')
        time.sleep(15) #Make sure this is shorter than watchdog timeout
        # supervisor.reload()
        microcontroller.reset()