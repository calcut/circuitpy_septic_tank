import time
import board
from mcu import Mcu
import digitalio
import adafruit_htu31d

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging

print('imported libraries')

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
AIO = True
# AIO = False

DEMO = False

def main():


    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x40' : 'Temp/Humidity HTU31D',

    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu(display=None)

    # Choose minimum logging level to process
    mcu.log.level = logging.INFO #i.e. ignore DEBUG messages
    
    # Example of log messages at different levels,
    # use these instead of print() for more control.
    if DEMO:
        mcu.log.critical(f"test") 
        mcu.log.error(f"test")
        mcu.log.warning(f"test") 
        mcu.log.info(f"ping")  #Will not be sent to AIO log feed, use as default
        mcu.log.debug(f"ping") #Will not be sent to AIO log feed

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    # instantiate i2c devices
    try:
        htu = adafruit_htu31d.HTU31D(mcu.i2c)
        htu.heater = False
        mcu.log.info(f'found HTU31D')
        mcu.pixel[0] = mcu.pixel.GREEN
        mcu.pixel.brightness = 0.05

    except Exception as e:
        mcu.log.error(e)
        mcu.pixel[0] = mcu.pixel.RED

    # Setup for Latching Relay Featherwing 
    # These signals are set by soldering wires
    relay_set_pin = digitalio.DigitalInOut(board.D11)
    relay_set_pin.direction = digitalio.Direction.OUTPUT
    relay_set_pin.value = False

    relay_unset_pin = digitalio.DigitalInOut(board.D12)
    relay_unset_pin.direction = digitalio.Direction.OUTPUT
    relay_unset_pin.value = False

    heating_requested = "OFF"

    # Store an initial target temperature as an attribute of the mcu object
    # This saves it for access from other functions
    mcu.temperature_target = 16

    if AIO:

        mcu.wifi_connect()
        mcu.aio_setup(log_feed='relay-logging')
        mcu.subscribe("target-temperature")

    def parse_feeds():
        if mcu.aio_connected:
            for feed_id in mcu.feeds.keys():
                payload = mcu.feeds.pop(feed_id)

                if feed_id == 'target-temperature':
                    mcu.temperature_target = float(payload)

    def publish_feeds():
        # AIO limits to 30 data points per minute in the free version
        # Set publish interval accordingly
        feeds = {}
        if mcu.aio_connected:
            feeds['temperature-hallway'] = round(htu.temperature, 2)
            feeds['humidity-hallway'] = round(htu.relative_humidity, 2)
            # feeds['heating-requested'] = heating_requested
            #This will automatically limit its rate to not get throttled by AIO
            mcu.aio_send(feeds, aio_plus=False)


    timer_100ms = 0
    timer_1s = 0
    timer_30s = 0

    while True:

        if (time.monotonic() - timer_100ms) >= 0.1:
            timer_100ms = time.monotonic()
            mcu.watchdog.feed()
            mcu.aio_receive()
            parse_feeds()

        if (time.monotonic() - timer_1s) >= 1:
            timer_1s = time.monotonic()
            mcu.led.value = not(mcu.led.value)

            # 0.2 degrees hysteresis
            if heating_requested == "OFF":
                if htu.temperature < mcu.temperature_target -0.2:
                    mcu.log.warning((f'Temperature={htu.temperature:0.1f}C '
                                    + f'Target={mcu.temperature_target:0.1f}C '
                                    + f'turning heating on'))
                    relay_unset_pin.value = False
                    relay_set_pin.value = True
                    heating_requested = "ON"
                    mcu.io.publish('heating-requested', heating_requested)
            else:
                if htu.temperature > mcu.temperature_target +0.2:
                    mcu.log.warning(f'Temperature={htu.temperature:0.1f}C '
                                    + f'Target={mcu.temperature_target:0.1f}C '
                                    + 'turning heating off')
                    relay_set_pin.value = False
                    relay_unset_pin.value = True
                    heating_requested = "OFF"
                    mcu.io.publish('heating-requested', heating_requested)
            
        if (time.monotonic() - timer_30s) >= 30:
            timer_30s = time.monotonic()            
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

    # except Exception as e:
    #     print(f'caught exception {e}')
    #     time.sleep(5)
    #     supervisor.reload()
