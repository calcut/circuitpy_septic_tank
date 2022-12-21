import time
import board
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.display import LCD_20x4
from circuitpy_septic_tank.gascard import Gascard
from adafruit_motorkit import MotorKit
import busio

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/calcut/circuitpy-septic_tank"
__filename__ = "methane_gascard.py"

NUM_PUMPS = 4
LOGLEVEL = logging.DEBUG

# global variable so pumps can be shut down after keyboard interrupt
pumps_in = []
pumps_out = []

def main():

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x70' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4
        '0x72' : 'Sparkfun LCD Display',
        # '0x40' : 'Temp/Humidity HTU31D',

    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu(loglevel=LOGLEVEL, i2c_freq=100000)

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    try:
        global pumps_in
        global pumps_out
        # Changing pwm freq from 1600Hz to <500Hz helps a lot with matching speeds. unsure exactly why. 
        pump_driver_out = MotorKit(i2c=mcu.i2c, address=0x6E, pwm_frequency=400)
        pump_driver_in = MotorKit(i2c=mcu.i2c, address=0x6F, pwm_frequency=400)
        pumps_in = [pump_driver_in.motor1, pump_driver_in.motor2, pump_driver_in.motor3, pump_driver_in.motor4]
        pumps_out = [pump_driver_out.motor1, pump_driver_out.motor2, pump_driver_out.motor3, pump_driver_out.motor4]

        # Drop any unused pumps as defined by the num-pumps environment variable
        pumps_in = pumps_in[:NUM_PUMPS]
        pumps_out = pumps_out[:NUM_PUMPS]

        for p in pumps_in:
            p.throttle = 0
        for p in pumps_out:
            p.throttle = 0
        
    except Exception as e:
        mcu.handle_exception(e)
        mcu.log.warning('Pump driver not found')


    try:
        display = LCD_20x4(mcu.i2c)
        mcu.attach_display(display)
        display.show_text(__filename__)
        display.set_cursor(0,2)
        display.write('Waiting for Gascard')
    except Exception as e:
        mcu.log.warning(f"display error: {e}")

    try:
        uart = busio.UART(board.TX, board.RX, baudrate=57600)
        gc = Gascard(uart)
        gc.log.addHandler(mcu.loghandler)
        gc.log.setLevel(logging.INFO)
        mcu.watchdog_feed() #gascard startup can take a while
        gc.poll_until_ready()
        mcu.watchdog_feed() #gascard startup can take a while

    except Exception as e:
        mcu.handle_exception(e)
        mcu.log.warning('Gascard not found')
        raise

    # Display Gascard Settings

    # display.clear()
    # display.write(f'Gascard FW={gc.firmware_version}')
    # display.set_cursor(0,1)
    # display.write(f'Serial Num={gc.serial_number}')
    # display.set_cursor(0,2)
    # display.write(f'conf={gc.config_register} freq={gc.frequency}')
    # display.set_cursor(0,3)
    # display.write(f'TC={gc.time_constant} SW={gc.switches_state}')
    # time.sleep(5)

  
    # Setup labels to be displayed on LCD
    display.labels[0]='CH4 Conc='
    display.labels[1]='Pressure='
    # display.labels[2]='Sample='
    # display.labels[3]='Reference='

    def update_display():
        display.values[0] = f'{gc.concentration:7.4f}%'
        display.values[1] = f'{gc.pressure:6.1f} '
        # display.values[2] = f'{gc.sample} '
        # display.values[3] = f'{gc.reference} '
        display.show_data_long()

    def run_pump(index, speed=None, duration=None):

        pumps_in[index-1].throttle = speed
        pumps_out[index-1].throttle = speed
        if duration:
            mcu.log.info(f'running pump{index} at speed={speed} for {duration}s')
            time.sleep(duration)
            pumps_in[index-1].throttle = 0
            pumps_out[index-1].throttle = 0
        else:
            mcu.log.info(f'running pump{index} at speed={speed}')


    def usb_serial_parser(string):
        if string.startswith('p'):
            settings = string[1:].split()
            try:
                index = int(settings[0])
                speed = float(settings[1])
                if len(settings) > 2:
                    duration = int(settings[2])
                else:
                    duration = None
                run_pump(index, speed, duration)
            except Exception as e:
                print(e)
                mcu.handle_exception(e)
                mcu.log.warning(f'string {string} not valid for pump settings\n'
                                 +'input pump settings in format "p pump_number speed duration" e.g. p ')

        else:
            print(f'Writing to Gascard [{string}]')
            gc.write_command(string)

    timer_A = time.monotonic()
    timer_B = time.monotonic()
    timer_C = time.monotonic()

    while True:

        # Allows keyboard commands to be routed to the Gascard
        mcu.service(serial_parser=usb_serial_parser)

        # Check for incoming serial messages from Gascard
        data_string = gc.parse_serial()


        if time.monotonic() - timer_A > 1:
            timer_A = time.monotonic()
            print(data_string)
            update_display()

if __name__ == "__main__":
    try:
        enable_watchdog(timeout=120)
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for p in pumps_in:
            p.throttle = 0
        for p in pumps_out:
            p.throttle = 0

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        for p in pumps_in:
            p.throttle = 0
        for p in pumps_out:
            p.throttle = 0
        reset(e)