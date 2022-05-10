import time
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.display import LCD_20x4
from circuitpy_mcu.DFRobot_PH import DFRobot_PH
import adafruit_mcp9600
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_motorkit import MotorKit

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
# AIO = False

PH_CHANNELS = 3

def main():

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x48' : 'ADC for pH Probes ADC1115',
        '0x60' : 'Thermocouple Amp MCP9600',
        '0x61' : 'Thermocouple Amp MCP9600',
        '0x62' : 'Thermocouple Amp MCP9600',
        '0x63' : 'Thermocouple Amp MCP9600',
        '0x64' : 'Thermocouple Amp MCP9600',
        '0x65' : 'Thermocouple Amp MCP9600',
        '0x66' : 'Thermocouple Amp MCP9600',
        '0x67' : 'Thermocouple Amp MCP9600',
        '0x68' : 'Realtime Clock PCF8523', # On Adalogger Featherwing
        '0x72' : 'Sparkfun LCD Display',
        '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu()

    # Choose minimum logging level to process
    mcu.log.setLevel(logging.INFO) #i.e. ignore DEBUG messages

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)


    # Instantiate i2c display
    try:
        display = LCD_20x4(mcu.i2c)
        mcu.attach_display(display) # to show wifi/AIO status etc.
        display.show_text(__filename__) # shows current filename
        mcu.log.info(f'found Display')
    except Exception as e:
        mcu.log_exception(e)


    # Instantiate thermocouple probes 
    tc_addresses = [0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67]
    tc_channels = []

    for addr in tc_addresses:
        try:
            tc = adafruit_mcp9600.MCP9600(mcu.i2c, address=addr)
            tc_channels.append(tc)
            print(f'Found thermocouple channel at address {addr:x}')
        except Exception as e:
            mcu.log.info(f'No thermocouple channel at {addr:x}')

    # Instantiate ph channels
    ph_channels = []
    try:
        ph_converter = DFRobot_PH()
        ads = ADS.ADS1115(mcu.i2c)
        ph_channels.append(AnalogIn(ads, ADS.P0))
        ph_channels.append(AnalogIn(ads, ADS.P1))
        ph_channels.append(AnalogIn(ads, ADS.P2))
        ph_channels.append(AnalogIn(ads, ADS.P3))

        # Drop any unwanted/unused channels, as specified by PH_CHANNELS
        ph_channels = ph_channels[:PH_CHANNELS] 

    except Exception as e:
        mcu.log.info('ADC for pH probes not found')

    mcu.watchdog.feed()
    mcu.attach_sdcard()
    mcu.archive_file('log.txt')
    mcu.archive_file('data.txt')
    mcu.watchdog.feed()

    if AIO:
        mcu.wifi_connect()
        mcu.aio_setup(log_feed=None)

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
        # AIO limits to 30 data points per minute and 10 feeds in the free version
        if mcu.aio_connected and len(mcu.data) > 0:

            # Optionally filter e.g. to get <10 feeds
            data = filter_data('TC', decimal_places=3)

            # location = "57.2445673, -4.3978963, 220" #Gorthleck, as an example

            #This will automatically limit its rate to not get throttled by AIO
            mcu.aio_send(data, location=None)

    def log_sdcard():
        if mcu.sdcard:
            text = f'{mcu.get_timestamp()} '

            text += ' TC:'
            data = filter_data('TC', decimal_places=3)
            for key in sorted(data):
                text+= f' {data[key]:.3f}'

            text += ' PH:'
            data = filter_data('PH', decimal_places=3)
            for key in sorted(data):
                text+= f' {data[key]:.3f}'
            try:
                with open('/sd/data.txt', 'a') as f:
                    f.write(text+'\n')
                    mcu.log.info(f'{text} -> /sd/data.txt')
            except OSError as e:
                print(f'SDCARD FS not writable {e}')

    def capture_data():
        mcu.data = {}

        for ph in ph_channels:
            i = ph_channels.index(ph)
            mcu.data[f'PH{i+1}'] = ph_converter.read_PH(ph.voltage*1000)
            
        for tc in tc_channels:
            i = tc_channels.index(tc)
            mcu.data[f'TC{i+1}'] = tc.temperature

    def filter_data(filter_string=None, decimal_places=1):

        data = {}
        for key, value in mcu.data.items():
            if filter_string:
                if key.startswith(filter_string):
                    data[key] = round(value, decimal_places)
            else:
                data[key] = round(value, decimal_places)

        return data


    timer_A = 0
    timer_B = 0
    timer_C = 0
    display_page = 1

    while True:
        mcu.read_serial()

        if (time.monotonic() - timer_A) >= 5:
            timer_A = time.monotonic()
            if display_page == 1 and len(ph_channels) > 0:
                display_page = 2
            else:
                display_page = 1

        if (time.monotonic() - timer_B) >= 1:
            timer_B = time.monotonic()
            mcu.watchdog.feed()
            capture_data()
            mcu.aio_receive()
            parse_feeds()
            if display_page == 1:
                data =  filter_data('TC', decimal_places=1)
            if display_page == 2:
                data =  filter_data('PH', decimal_places=1)
            display.show_data_20x4(data)

        if (time.monotonic() - timer_C) >= 30:
            timer_C = time.monotonic()
            publish_feeds()
            log_sdcard()

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