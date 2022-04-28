import time
import board
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.display import LCD_20x4
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
AIO = True
# AIO = False

class Gascard():
    def __init__(self, uart):

        # Change this to a real logger after instanciation, if logging is needed
        self.log = logging.NullLogger()

        self.uart = uart
        self.ready = False
        self.timer = time.monotonic()
        self.mode = None

        self.sample = None
        self.reference = None
        self.concentration = None
        self.temperature = None
        self.pressure = None

        self.firmware_version = None
        self.serial_number = None
        self.config_register = None
        self.frequency = None
        self.time_constant = None
        self.switches_state = None

        self.restart()
        while not self.ready:
            self.parse_serial()

        self.read_settings()
        
    def write_command(self, string):
        command_bytes = bytearray(string)
        self.uart.write(command_bytes + bytearray('\r'))

        # rough code to check for acknowledgement
        # This isn't foolproof and can warn even when command has worked
        # But it does provide a suitable delay
        response = None
        i=0
        while response != command_bytes:
            response = self.uart.read(len(command_bytes))
            i += 1
            if i >= 5:
                if self.ready:
                    self.log.debug(f'warning, no acknowledgment of command {string}')
                return
        self.log.debug(f'command {string} acknowledged')

    def restart(self):
        self.ready = False
        self.write_command('X')
        self.write_command('q')

    def read_serial(self):
        data = self.uart.readline()
        if data is not None:
            data_string = ''.join([chr(b) for b in data])
            if data_string.endswith('\r\n'):
                data_string = data_string[:-2]  #drop the \r\n from the string       
            self.timer = time.monotonic()
            return data_string
        else:
            time_since_data = time.monotonic() - self.timer
            if time_since_data > 5:
                self.log.warning(f'No data from gascard in {time_since_data} seconds')
                self.ready = False
            return None

    def parse_serial(self):
        data_string = self.read_serial()

        if not data_string:
            return

        if not self.ready:
            if data_string[:33] == ' Waiting for application S-Record':
                self.log.info('Gascard found, starting up... (10s)')
            if data_string[:33] == ' Application started from address':
                self.ready = True
                self.log.info('Gascard ready')
            return

        if data_string[0:2] == 'N ':
            self.mode='Normal'
        elif data_string[0:2] == 'N1':
            self.mode='Normal Channel'
        elif data_string[0:2] == 'X ':
            self.mode='Settings'
        else:
            self.mode = None

        if self.mode == 'Normal':
            self.log.info('switching to N1 Channel Mode')
            self.write_command('N1')

        if self.mode == 'Normal Channel':
            data = data_string.split(' ')
            if len(data) == 7:
                self.sample = int(data[1])
                self.reference = int(data[2])
                self.concentration = float(data[4])
                self.temperature = int(data[5])
                self.pressure = float(data[6])

        if self.mode == 'Settings':
            data = data_string.split(' ')
            if len(data) == 7:
                self.firmware_version = data[1]
                self.serial_number = data[2]
                self.config_register = data[3]
                self.frequency = data[4]
                self.time_constant = data[5]
                self.switches_state = data[6]

        self.log.debug(f'{data_string}')
        return data_string


    def read_settings(self):
        self.write_command('X')
        while self.mode != 'Settings':
            self.parse_serial()
        self.log.info(f'{self.firmware_version=} '
                +f'{self.serial_number=} '
                +f'{self.config_register=} '
                +f'{self.frequency=} '
                +f'{self.time_constant=} '
                +f'{self.switches_state=}')
        self.write_command('N1')


def main():

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x72' : 'Sparkfun LCD Display',
        # '0x40' : 'Temp/Humidity HTU31D',

    }

    uart = busio.UART(board.TX, board.RX, baudrate=57600)

    # instantiate the MCU helper class to set up the system
    mcu = Mcu()

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    try:
        display = LCD_20x4(mcu.i2c)
        mcu.attach_display(display)
        display.show_text(__filename__)
        display.set_cursor(0,2)
        display.write('Waiting for Gascard')

        gc = Gascard(uart)
        mcu.watchdog.feed() #gascard startup can take a while

    except Exception as e:
        mcu.log_exception(e)
        mcu.pixel[0] = mcu.pixel.RED

   
    gc.log = logging.getLogger('Gascard')
    gc.log.addHandler(mcu.loghandler)
    gc.log.setLevel(logging.INFO)

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

    timer_A = time.monotonic()
    timer_B = time.monotonic()

    while True:

        # Allows keyboard commands to be routed to the Gascard
        mcu.read_serial(send_to=gc.write_command)
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
                print(f'N1 {gc.sample=} {gc.reference=} {gc.concentration=} {gc.pressure=}')

        if time.monotonic() - timer_B > 10:
            timer_B = time.monotonic()
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
        # print('Performing hard reset')
        # time.sleep(2)
        # microcontroller.reset()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        print(traceback.format_exception(None, e, e.__traceback__))
        # Can we log here?
        print('Performing a hard reset in 15s')
        time.sleep(15) #Make sure this is shorter than watchdog timeout
        # supervisor.reload()
        # microcontroller.reset()
