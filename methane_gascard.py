import time
import board
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

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
# AIO = True
AIO = False
NUM_PUMPS = 2


def main():

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x70' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4
        '0x72' : 'Sparkfun LCD Display',
        # '0x40' : 'Temp/Humidity HTU31D',

    }

    uart = busio.UART(board.TX, board.RX, baudrate=57600)

    # instantiate the MCU helper class to set up the system
    mcu = Mcu()

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    try:
        pump_driver = MotorKit(i2c=mcu.i2c, address=0x70)
        pumps = [pump_driver.motor1, pump_driver.motor2, pump_driver.motor3, pump_driver.motor4]
        # Drop any unused pumps as defined by the NUM_PUMPS parameter
        pumps = pumps[:NUM_PUMPS]

    except:
        mcu.log.warning('Pump driver not found')

    try:
        display = LCD_20x4(mcu.i2c)
        mcu.attach_display(display)
        display.show_text(__filename__)
        display.set_cursor(0,2)
        display.write('Waiting for Gascard')

        gc = Gascard(uart)
        gc.log = logging.getLogger('Gascard')
        gc.log.addHandler(mcu.loghandler)
        gc.log.setLevel(logging.INFO)
        gc.restart()
        mcu.watchdog.feed() #gascard startup can take a while

    except Exception as e:
        mcu.log_exception(e)
        mcu.pixel[0] = mcu.pixel.RED

   


    # Display Gascard Settings

    display.clear()
    display.write(f'Gascard FW={gc.firmware_version}')
    display.set_cursor(0,1)
    display.write(f'Serial Num={gc.serial_number}')
    display.set_cursor(0,2)
    display.write(f'conf={gc.config_register} freq={gc.frequency}')
    display.set_cursor(0,3)
    display.write(f'TC={gc.time_constant} SW={gc.switches_state}')
    time.sleep(5)

    if AIO:
        mcu.wifi_connect()
        mcu.aio_setup(log_feed=None)
        # mcu.subscribe("target-temperature")

    def parse_feeds():
        if mcu.aio_connected:
            for feed_id in mcu.feeds.keys():
                payload = mcu.feeds.pop(feed_id)

                # if feed_id == 'target-temperature':
                #     mcu.temperature_target = float(payload)

    def publish_feeds():
        # AIO limits to 30 data points per minute in the free version
        feeds = {}
        if mcu.aio_connected:
            feeds['methane1'] = gc.concentration

            # In order to prevent being throttled by AIO, aio_send() will not 
            # publish if called too often.  Try to avoid sending
            # more than 30 updates per minute
            mcu.aio_send(feeds)
  
    # Setup labels to be displayed on LCD
    display.labels[0]='CH4 Conc='
    display.labels[1]='Pressure='
    display.labels[2]='Sample='
    display.labels[3]='Reference='

    def update_display():
        display.values[0] = f'{gc.concentration:7.4f}%'
        display.values[1] = f'{gc.pressure:6.1f} '
        display.values[2] = f'{gc.sample} '
        display.values[3] = f'{gc.reference} '
        display.show_data_long()

    def run_pump(index, speed=None, duration=None):
        
        pumps[index-1].throttle = speed
        if duration:
            mcu.log.info(f'running pump{index} at speed={speed} for {duration}s')
            time.sleep(duration)
            pumps[index-1].throttle = 0
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
        mcu.read_serial(send_to=usb_serial_parser)
        mcu.watchdog.feed()

        # Check for incoming serial messages from Gascard
        data_string = gc.parse_serial()

        if gc.mode != 'Normal Channel':
            print(data_string)

        if time.monotonic() - timer_A > 1:
            timer_A = time.monotonic()
            update_display()
            parse_feeds()
            if gc.mode == 'Normal Channel':
                pass
                # print(f'N1 {gc.sample=} {gc.reference=} {gc.concentration=} {gc.pressure=}')

        if time.monotonic() - timer_B > 10:
            timer_B = time.monotonic()
            publish_feeds()

        # Some sort of timing control for pumps
        if time.monotonic() - timer_C > 10:
            timer_C = time.monotonic()
            # if pumps[0].throttle:
            #     pumps[0].throttle = None
            # else:
            #     run_pump(1, 0.6)


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
