import time
from circuitpy_mcu.mcu import Mcu

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/calcut/circuitpy-septic_tank"
__filename__ = "septic_tank.py"

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
AIO = True

AIO_GROUP = 'septic-dev'
LOGLEVEL = logging.INFO



def main():

    # instantiate the MCU helper class to set up the system
    mcu = Mcu(watchdog_timeout=20)

    # Choose minimum logging level to process
    mcu.log.setLevel(LOGLEVEL)

 
    mcu.watchdog.feed()

    if AIO:
        mcu.wifi_connect()
        mcu.aio_setup(log_feed='log', group=AIO_GROUP)


        
        mcu.subscribe(f'{AIO_GROUP}.pump1-speed')
        mcu.subscribe(f'{AIO_GROUP}.pump2-speed')
        mcu.subscribe(f'{AIO_GROUP}.pump3-speed')
        mcu.subscribe(f'{AIO_GROUP}.gc1')
        mcu.subscribe(f'{AIO_GROUP}.gc2')
        mcu.subscribe(f'{AIO_GROUP}.gc3')
        mcu.subscribe(f'{AIO_GROUP}.tc1')
        mcu.subscribe(f'{AIO_GROUP}.tc2')
        mcu.subscribe(f'{AIO_GROUP}.tc3')
        mcu.subscribe(f'{AIO_GROUP}.tc4')
        mcu.subscribe(f'{AIO_GROUP}.ph1')
        mcu.subscribe(f'{AIO_GROUP}.ph2')
        mcu.subscribe(f'{AIO_GROUP}.ph3')

 
    mcu.log.info(f'BOOT complete at {mcu.get_timestamp()}')
    time.sleep(2)
    supervisor.reload()

 
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
        # time.sleep(15)
        # microcontroller.reset()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        print(traceback.format_exception(None, e, e.__traceback__))
        # Can we log here?
        print('Performing a hard reset in 15s')
        # time.sleep(15) #Make sure this is shorter than watchdog timeout
        # supervisor.reload()
        # microcontroller.reset()
