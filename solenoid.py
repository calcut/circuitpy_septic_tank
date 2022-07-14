from adafruit_motorkit import MotorKit
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.aio import Aio_http

import adafruit_pcf8523
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

    mcu = Mcu()
    rtc = adafruit_pcf8523.PCF8523(mcu.i2c)

    try:
        global valves
        valve_driver = MotorKit(i2c=mcu.i2c, address=0x70)
        valves = [valve_driver.motor1, valve_driver.motor2, valve_driver.motor3, valve_driver.motor4]

        # Drop any unused valves as defined by the NUM_VALVES parameter
        valves = valves[:NUM_VALVES]
        
    except Exception as e:
        mcu.log_exception(e)
        mcu.log.warning('valve driver not found')


    def toggle_valve(index):
        global valves
        mcu.log.info(f'Toggling valve {index}')
        if valves[index].throttle == 1:
            close_valve(index)
        else:
            open_valve(index)

    def open_valve(index):
        global valves
        valves[index].throttle = 1
        mcu.log.info(f'Opening Valve {index}')

    def close_valve(index):
        global valves
        valves[index].throttle = 0
        mcu.log.info(f'Closing Valve {index}')


    def usb_serial_parser(string):
        global valves

        if string.startswith('v'):
            try:
                index = int(string[1])
                toggle_valve(index)

            except Exception as e:
                print(e)
                mcu.log.warning(f'string {string} not valid for valve settings\n'
                                 +'input valve settings in format "v valve_number" e.g. v0')

    rtc.datetime = time.struct_time((2017,1,9,15,6,0,0,9,-1))

    rtc.alarm = (time.struct_time((2017,1,9,15,6,0,0,19,-1)), "daily")
    rtc.alarm2 = (time.struct_time((2017,1,9,16,6,0,0,19,-1)), "daily")

    timer_A = 0
    while True:
        mcu.read_serial(send_to=usb_serial_parser)
        microcontroller.watchdog.feed()
        if time.monotonic() - timer_A > 1:
            print('')

            timer_A = time.monotonic()
            # print(mcu.get_timestamp())

            
            print(rtc.datetime)
            print(f'{rtc.alarm_status=}')
            if rtc.alarm_status:
                rtc.alarm_status = False
                print('cancelling alarm!')

            """
            TODO 
            Get RTC chip working, needs battery really
            concept of pulsing mode. pulsing on/off for 8 mins.

            
            """


if __name__ == "__main__":
    try:
        enable_watchdog(timeout=60)
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for v in valves:
            v.throttle = 0

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        reset(e)