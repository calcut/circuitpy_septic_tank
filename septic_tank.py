import time
import board
from mcu import Mcu
import adafruit_mcp9600
from adafruit_motorkit import MotorKit
from analogio import AnalogIn

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
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
    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    # instantiate i2c devices
    try:
        probe0 = adafruit_mcp9600.MCP9600(mcu.i2c, address=0x60)
        print(f'found probe0')
        pump = MotorKit(i2c=mcu.i2c, address=0x70)
        print('found motor featherwing')
        mcu.pixel[0] = mcu.pixel.GREEN
        mcu.pixel.brightness = 0.05

    except Exception as e:
        print(e)
        mcu.pixel[0] = mcu.pixel.RED

    # Setup labels to be displayed on LCD
    mcu.display.labels[0]='  T0='
    mcu.display.labels[1]='  T1='
    mcu.display.labels[2]='  T2='
    mcu.display.labels[3]=' AD0='

    if AIO:

        mcu.wifi_connect()
        mcu.aio_setup()
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
                    mcu.display.setFastBacklight(r, g, b)

                if feed_id == 'target-temperature':
                    temp_target = int(payload)
                    # Nothing is done with this currently

                if feed_id == 'dac-voltage':
                    dac.voltage = float(payload)
                    dac.value = int(dac.voltage/5 * 65535)

    def publish_feeds():
        # AIO limits to 30 data points per minute in the free version
        # Set publish interval accordingly
        feeds = {}
        if mcu.aio_connected:
            feeds['temperature0'] = round(probe0.temperature, 2)
            location = "57.2445673, -4.3978963, 220" #Gorthleck, as an example

            #This will automatically limit its rate to not get throttled by AIO
            mcu.aio_send(feeds, location, aio_plus=False)

    def update_display():
        #ADC max value 50819 and max voltage 2.55V has been determined manually
        #This may vary board to board.

        # mcu.display.values[0] = f'{probe0.temperature: 4.1f} '
        # mcu.display.values[1] = f'{probe1.temperature: 4.1f} '
        # mcu.display.values[2] = f'{probe2.temperature: 4.1f} '
        # mcu.display.values[3] = f'{ADC0_voltage: 4.2f} '
        # mcu.display.values[4] = f'{ADC1_voltage: 4.2f} '
        # mcu.display.values[5] = f'{dac.voltage: 4.2f} '
        mcu.display.values[6] = f''
        mcu.display.values[7] = f''
        mcu.display.show_data_16x2()


    timer_100ms = 0
    timer_1s = 0

    pump.motor1.throttle = 0.6
    pump.motor2.throttle = 0
    pump.motor3.throttle = 0
    pump.motor4.throttle = 0
    print('driving motor1')

    while True:

        if (time.monotonic() - timer_100ms) >= 0.1:
            timer_100ms = time.monotonic()

            mcu.watchdog.feed()
            mcu.aio_receive()
            parse_feeds()

        if (time.monotonic() - timer_1s) >= 1:
            timer_1s = time.monotonic()

            update_display()
            publish_feeds()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        
    except WatchDogTimeout:
        print('Code Stopped by WatchDog Timeout!')
        # supervisor.reload()
        # NB, sometimes soft reset is not enough! need to do hard reset here
        print('Performing hard reset')
        time.sleep(2)
        microcontroller.reset()

    except Exception as e:
        print(f'caught exception {e}')
        traceback.print_exception(e, e, e.__traceback__)
        # time.sleep(5)
        # supervisor.reload()