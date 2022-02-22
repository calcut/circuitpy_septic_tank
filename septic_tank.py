import time
import board
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.display import LCD_16x2
import adafruit_mcp9600
from adafruit_motorkit import MotorKit
from analogio import AnalogIn

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback

print('imported libraries')

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
# AIO = True
AIO = False

def main():

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x60' : 'Thermocouple Amp MCP9600',
        '0x62' : 'DAC MCP4725',
        '0x70' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4
        '0x72' : 'Sparkfun LCD Display',
        '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu()

    # Choose minimum logging level to process
    mcu.log.setLevel(logging.INFO) #i.e. ignore DEBUG messages

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    # instantiate i2c devices
    try:
        display = LCD_16x2(mcu.i2c)
        mcu.attach_display(display) # to show wifi/AIO status etc.
        display.show_text(__file__) # shows current filename
        mcu.log.info(f'found Display')
        probe0 = adafruit_mcp9600.MCP9600(mcu.i2c, address=0x60)
        mcu.log.info(f'found probe0')
        pump = MotorKit(i2c=mcu.i2c, address=0x70)
        mcu.log.info('found motor featherwing')
        mcu.pixel[0] = mcu.pixel.GREEN
        mcu.pixel.brightness = 0.05

    except Exception as e:
        mcu.log_exception(e)
        mcu.pixel[0] = mcu.pixel.RED

    # Setup labels to be displayed on LCD
    display.labels[0]='T0='
    display.labels[1]='T1='
    display.labels[2]='T2='
    display.labels[3]='AD0='

    if AIO:

        mcu.wifi_connect()
        mcu.aio_setup(log_feed=None)
        mcu.subscribe('led-color')
        mcu.subscribe("dac-voltage")
        mcu.subscribe("target-temperature")

    def parse_feeds():
        if mcu.aio_connected:
            for feed_id in mcu.feeds.keys():
                payload = mcu.feeds.pop(feed_id)

                if feed_id == 'led-color':
                    r = int(payload[1:3], 16)
                    g = int(payload[3:5], 16)
                    b = int(payload[5:], 16)
                    display.set_fast_backlight_rgb(r, g, b)

                if feed_id == 'target-temperature':

                    temp_target = float(payload)
                    # Nothing is done with this currently

    def publish_feeds():
        # AIO limits to 30 data points per minute in the free version
        # Set publish interval accordingly
        feeds = {}
        if mcu.aio_connected:
            feeds['temperature0'] = round(probe0.temperature, 2)
            location = "57.2445673, -4.3978963, 220" #Gorthleck, as an example

            #This will automatically limit its rate to not get throttled by AIO
            mcu.aio_send(feeds, location)

    def update_display():
        #ADC max value 50819 and max voltage 2.55V has been determined manually
        #This may vary board to board.

        display.values[0] = f'{probe0.temperature:4.1f} '
        # display.values[1] = f'{probe1.temperature: 4.1f} '
        # display.values[2] = f'{probe2.temperature: 4.1f} '
        # display.values[3] = f'{ADC0_voltage: 4.2f} '
        # display.values[4] = f'{ADC1_voltage: 4.2f} '
        # display.values[5] = f'{dac.voltage: 4.2f} '
        # display.values[6] = f''
        # display.values[7] = f''
        display.show_data()


    timer_A = 0
    timer_B = 0
    timer_C = 0

    pump.motor1.throttle = 0.6
    mcu.log.info('driving pump')
    # pump.motor2.throttle = 0
    # pump.motor3.throttle = 0
    # pump.motor4.throttle = 0

    while True:
        mcu.read_serial()

        if (time.monotonic() - timer_A) >= 0.1:
            timer_A = time.monotonic()

        if (time.monotonic() - timer_B) >= 1:
            timer_B = time.monotonic()
            mcu.watchdog.feed()
            mcu.aio_receive()
            parse_feeds()
            update_display()

        if (time.monotonic() - timer_C) >= 30:
            timer_C = time.monotonic()
            publish_feeds()


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
        print('Performing hard reset')
        time.sleep(2)
        microcontroller.reset()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        print(traceback.format_exception(None, e, e.__traceback__))
        # Can we log here?
        # print('Performing a hard reset in 15s')
        # time.sleep(15) #Make sure this is shorter than watchdog timeout
        # supervisor.reload()
        # microcontroller.reset()