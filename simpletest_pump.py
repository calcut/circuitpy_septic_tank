import time
import board
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.display import LCD_20x4
import busio
from adafruit_motorkit import MotorKit

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/calcut/circuitpy-septic_tank"
__filename__ = "pump.py"

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
# AIO = True
AIO = False

def main():

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x72' : 'Sparkfun LCD Display',
        '0x70' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4
        # '0x40' : 'Temp/Humidity HTU31D',

    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu()

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    try:
        pump = MotorKit(i2c=mcu.i2c, address=0x70)
    except:
        mcu.log.warning('Pump driver not found')

    pump.motor1.throttle = 0.6
    pump.motor2.throttle = 0
    pump.motor3.throttle = 0
    pump.motor4.throttle = 0
    print('driving motor1')

    def motorspeed(string):
        speed = float(string)
        print(speed)
        pump.motor1.throttle = speed

    while True:
        mcu.read_serial(send_to=motorspeed)
        mcu.watchdog.feed()
    # time.sleep(10)
    # pump.motor1.throttle = 0.0

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        # May want to add code to stop gracefully here 
        # e.g. turn off relays or pumps
        
    except WatchDogTimeout:
        print('Code Stopped by WatchDog Timeout!')
        # supervisor.reload()
        # NB, sometimes soft reset is not enough! need to do hard reset here
        # print('Performing hard reset in 15s')
        # time.sleep(15)
        # microcontroller.reset()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        print(traceback.format_exception(None, e, e.__traceback__))
        # Can we log here?
        # print('Performing a hard reset in 15s')
        # time.sleep(15) #Make sure this is shorter than watchdog timeout
        # # supervisor.reload()
        # microcontroller.reset()