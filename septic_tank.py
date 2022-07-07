import time
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.display import LCD_20x4
from circuitpy_septic_tank.gascard import Gascard
from circuitpy_mcu.DFRobot_PH import DFRobot_PH
import adafruit_mcp9600
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_motorkit import MotorKit
import busio
import board

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback

__version__ = "1.0.1_http"
__repo__ = "https://github.com/calcut/circuitpy-septic_tank"
__filename__ = "septic_tank.py"

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
AIO = True
# AIO = False

GASCARD_SAMPLE_DURATION = 2 # minutes
GASCARD_INTERVAL = 10 # minutes
GASCARD = True
# GASCARD = False
NUM_PUMPS = 2
PH_CHANNELS = 1
AIO_GROUP = 'boness'
LOGLEVEL = logging.INFO
# LOGLEVEL = logging.DEBUG

# DELETE_ARCHIVE = False
DELETE_ARCHIVE = True

# global variable so pumps can be shut down after keyboard interrupt
pumps = []
pump_index = 1

def main():

    # defaults, will be overwritten if connected to AIO
    pump_speeds = [0.5, 0.5, 0.5]

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
        '0x70' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4
        '0x72' : 'Sparkfun LCD Display',
        '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu(watchdog_timeout=60)
    mcu.booting = True # A flag to record boot messages
    mcu.log.info(f'STARTING {mcu.id} {__filename__} {__version__}')

    # Choose minimum logging level to process
    mcu.log.setLevel(LOGLEVEL)

    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)

    try:
        display = LCD_20x4(mcu.i2c)
        mcu.attach_display(display) # to show wifi/AIO status etc.
        display.show_text(__filename__) # shows current filename
        time.sleep(1)
        mcu.log.info(f'found Display')
    except Exception as e:
        mcu.log_exception(e)
        display = None

        
    mcu.attach_sdcard()
    if DELETE_ARCHIVE:
        mcu.delete_archive()
    mcu.archive_file('log.txt')
    mcu.archive_file('data.txt')
    mcu.watchdog.feed()

    if AIO:
        mcu.wifi_connect()
        mcu.aio_setup(log_feed='log', group=AIO_GROUP)
        mcu.subscribe('pump1-speed')
        mcu.aio_send_log() # Send the boot log so far


    def connect_thermocouple_channels():
        tc_addresses = [0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67]
        tc_channels = []

        for addr in tc_addresses:
            try:
                tc = adafruit_mcp9600.MCP9600(mcu.i2c, address=addr)
                tc_channels.append(tc)
                mcu.log.info(f'Found thermocouple channel at address {addr:x}')
                
            except Exception as e:
                mcu.log.info(f'No thermocouple channel at {addr:x}')

        return tc_channels

    def connect_ph_channels():
        try:
            ph_channels = []
            ads = ADS.ADS1115(mcu.i2c)
            adc_list = [ADS.P0, ADS.P1, ADS.P2, ADS.P3]

            # Drop any unwanted/unused channels, as specified by PH_CHANNELS
            adc_list = adc_list[:PH_CHANNELS] 

            for ch in adc_list:
                ph_channel = DFRobot_PH(
                    analog_in = AnalogIn(ads, ch),
                    calibration_file= f'/sd/ph_calibration_ch{ch+1}.txt',
                    log_handler = mcu.loghandler
                    )
                ph_channels.append(ph_channel)

        except Exception as e:
            mcu.log_exception(e)
            mcu.log.info('ADC for pH probes not found')

        return ph_channels


    def connect_pumps():
        try:
            global pumps
            pump_driver = MotorKit(i2c=mcu.i2c, address=0x70)
            pumps = [pump_driver.motor1, pump_driver.motor2, pump_driver.motor3, pump_driver.motor4]

            # Drop any unused pumps as defined by the NUM_PUMPS parameter
            pumps = pumps[:NUM_PUMPS]
            
        except Exception as e:
            mcu.log_exception(e)
            mcu.log.warning('Pump driver not found')
        
        return pumps

    def connect_gascard():
        try:
            uart = busio.UART(board.TX, board.RX, baudrate=57600)
            mcu.log.warning('Waiting for Gascard') #For debug really, can be removed
            gc = Gascard(uart)
            gc.log.addHandler(mcu.loghandler)
            gc.log.setLevel(LOGLEVEL)
            mcu.watchdog.feed() #gascard startup can take a while
            gc.restart()
            mcu.watchdog.feed() #gascard startup can take a while


        # Probably do not want this, as it effectively ignores some gascard errors
        # except WatchDogTimeout:
        #     print('Timed out waiting for Gascard')
        #     mcu.log.warning('Gascard not found')
        #     gc = None 

        except Exception as e:
            mcu.log_exception(e)
            mcu.log.warning('Gascard not found')
            raise

        return gc

    tc_channels = connect_thermocouple_channels()
    ph_channels = connect_ph_channels()
    pumps = connect_pumps()

    display.clear()
    display.write(f'{len(tc_channels)} TC channels')
    display.set_cursor(0,1)
    display.write(f'{len(ph_channels)} pH channels')
    display.set_cursor(0,2)
    display.write(f'{len(pumps)} air pumps')
    display.set_cursor(0,3)
    display.write(f'Waiting for gascard')

    if GASCARD:
        gc = connect_gascard()
    else:
        gc = None

    # Display gascard info
    if gc:
        display.clear()
        display.write(f'Gascard FW={gc.firmware_version}')
        display.set_cursor(0,1)
        display.write(f'Serial Num={gc.serial_number}')
        display.set_cursor(0,2)
        display.write(f'conf={gc.config_register} freq={gc.frequency}')
        display.set_cursor(0,3)
        display.write(f'TC={gc.time_constant} SW={gc.switches_state}')
    else:
        display.clear()
        display.write(f'Gascard not used')
    time.sleep(5)



    def parse_feeds():
        if mcu.aio_connected:
            for feed_id in mcu.updated_feeds.keys():
                payload = mcu.updated_feeds.pop(feed_id)

                if feed_id == 'led-color':
                    r = int(payload[1:3], 16)
                    g = int(payload[3:5], 16)
                    b = int(payload[5:], 16)
                    display.set_fast_backlight_rgb(r, g, b)

                if feed_id == f'pump1-speed':
                    pump_speeds[0] = float(payload)
                if feed_id == f'pump2-speed':
                    pump_speeds[1] = float(payload)
                if feed_id == f'pump3-speed':
                    pump_speeds[2] = float(payload)

                if feed_id == 'ota':
                    mcu.ota_reboot()

    def publish_feeds():
        # AIO limits to 30 data points per minute and 10 feeds in the free version
        if mcu.aio_connected and len(mcu.data) > 0:

            # Optionally filter e.g. to get <10 feeds
            # data = filter_data('TC', decimal_places=3)
            data = mcu.data

            # location = "57.2445673, -4.3978963, 220" #Gorthleck, as an example

            #This will automatically limit its rate to not get throttled by AIO
            mcu.aio_send(data, location=None)

            # don't keep transmitting this until next updated.
            if 'gc1' in mcu.data:
                del mcu.data['gc1'] # Simplified for one channel

    def log_sdcard():
        if mcu.sdcard:
            text = f'{mcu.get_timestamp()} '

            text += ' tc:'
            data = filter_data('tc', decimal_places=3)
            for key in sorted(data):
                text+= f' {data[key]:.3f}'

            text += ' ph:'
            data = filter_data('ph', decimal_places=2)
            for key in sorted(data):
                text+= f' {data[key]:.2f}'

            text += f' gc:'
            if gc:
                for p in pumps:
                    channel = f'gc{pumps.index(p) + 1}'
                    data = filter_data(f'{channel}', decimal_places=4)
                    if data:
                        text+= f' {data[channel]:.4f}'
                    else:
                        text+= ' --'
                    
            try:
                with open('/sd/data.txt', 'a') as f:
                    f.write(text+'\n')
                    mcu.log.info(f'{text} -> /sd/data.txt')
            except OSError as e:
                mcu.log.warning(f'SDCARD FS not writable {e}')

    def capture_data():

        # keep keys 'url safe', i.e.
        # lower case ASCII letters, numbers, dashes only

        for ph in ph_channels:
            i = ph_channels.index(ph)
            mcu.data[f'ph{i+1}'] = ph.read_PH()
            
        for tc in tc_channels:
            i = tc_channels.index(tc)
            mcu.data[f'tc{i+1}'] = tc.temperature

        # if gc:
        #     mcu.data[f'gc{pump_index}'] = gc.concentration

    def filter_data(filter_string=None, decimal_places=1):

        data = {}
        for key, value in mcu.data.items():
            if filter_string:
                if key.startswith(filter_string):
                    data[key] = round(value, decimal_places)
            else:
                data[key] = round(value, decimal_places)

        return data

    def interactive_ph_calibration():

        try:
            print('Calibration Mode, press Ctrl-C to exit')
            while True:
                # Need to sepcify how to get the temperature from a sensor here
                temperature = None
                valid_inputs = []
                for ch in ph_channels:
                    index = f'{ph_channels.index(ch)+1}'
                    valid_inputs.append(index)
                    ph = ch.read_PH()
                    print(f'Channel{index} pH={ph}, voltage={ch.adc.voltage}')

                print(f'Select channel to calibrate {valid_inputs}')
                line = mcu.get_serial_line(valid_inputs)
                ch_num = int(line)
                channel = ph_channels[ch_num-1]
                print(f'calibrating channel {ch_num}')

                if not temperature:
                    while True:
                        print(f'Enter the current temperature')
                        line = mcu.get_serial_line()
                        try:
                            temperature = float(line)
                            break
                        except Exception as e:
                            print(e)

                channel.calibrate(temperature)
        except KeyboardInterrupt:
            print('Leaving Calibration Mode')

    def display_summary():
        if gc:
            display.set_cursor(0,0)
            line = f'pump{pump_index}={pumps[pump_index-1].throttle}  {mcu.data["tc4"]:3.1f}C         '[:20]

            display.write(line[:20])

            display.set_cursor(0,1)
            line = ''
            data = filter_data('gc', decimal_places=4)
            for key in sorted(data):
                # display as float with max 4 decimal places, and max 7 chars long
                    line += f' {data[key]:.4f}'[:7]
            line = line[1:] #drop the first space, to keep within 20 chars
            display.write(line[:20])


        display.set_cursor(0,2)
        line = 'tc'
        data = filter_data('tc', decimal_places=1)
        data.pop('tc4', None) # Remove the ambient temperature thermocouple
        for key in sorted(data):
            line+= f' {data[key]:3.1f}'
        display.write(line[:20])

        display.set_cursor(0,3)
        line = 'ph'
        data = filter_data('ph', decimal_places=2)
        for key in sorted(data):
            line+= f' {data[key]:3.2f}'
        display.write(line[:20])

    def display_gascard_reading():
        display.labels[0]='CH4 Conc='
        display.labels[1]='Pressure='
        display.labels[2]='Sample='
        display.labels[3]='Reference='
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

    # def rotate_pumps():

    #     global pump_index
    #     pump_index += 1
    #     if pump_index > NUM_PUMPS:
    #         pump_index = 1

    #     # Stop all pumps
    #     for p in pumps:
    #         p.throttle = 0

    #     # start the desired pump
    #     speed = pump_speeds[pump_index - 1]
    #     pumps[pump_index-1].throttle = speed
    #     mcu.log.info(f'running pump{pump_index} at speed={speed}')


    def usb_serial_parser(string):
        if string == 'phcal':
            interactive_ph_calibration()

        elif string.startswith('p'):
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
            if gc:
                mcu.log.info(f'Writing to Gascard [{string}]')
                gc.write_command(string)

    timer_A = -GASCARD_INTERVAL*60
    timer_A1 = 0
    timer_B = 0
    timer_C = 0
    display.clear()
    mcu.log.info(f'BOOT complete at {mcu.get_timestamp()}')
    mcu.booting = False # Stop accumulating boot log messages
    mcu.aio_send_log() # Send the boot log

    while True:
        mcu.read_serial(send_to=usb_serial_parser)
        # Check for incoming serial messages from Gascard
        if gc:
            data_string = gc.parse_serial()
            # if gc.mode != 'Normal Channel':
            #     print(data_string)

        if (time.monotonic() - timer_A) >= GASCARD_INTERVAL*60:
            mcu.log.info(f'starting pump after GASCARD_INTERVAL = {GASCARD_INTERVAL}')
            # rotate_pumps()
            speed = pump_speeds[0]
            pumps[0].throttle = speed
            pumps[1].throttle = speed
            mcu.log.info(f'running pump 1 and 2 at speed={speed}')

            timer_A = time.monotonic()
            timer_A1 = time.monotonic()

        if time.monotonic() - timer_A1 > GASCARD_SAMPLE_DURATION*60:
            if gc:
                mcu.data[f'gc1'] = gc.concentration
                mcu.log.info(f'Capturing gascard sample')

            mcu.log.info(f'disabling pump after GASCARD_SAMPLE_DURATION = {GASCARD_SAMPLE_DURATION}')
            # Push timerA1 out into the future so this won't trigger again until after the next sample
            timer_A1 = timer_A + GASCARD_INTERVAL*60 *2
            pumps[0].throttle = 0
            pumps[1].throttle = 0


        if (time.monotonic() - timer_B) >= 1:
            timer_B = time.monotonic()
            mcu.watchdog.feed()

            capture_data()
            mcu.aio_receive()
            parse_feeds()
            display_summary()
            # display_gascard_reading()

        if (time.monotonic() - timer_C) >= 30:
            timer_C = time.monotonic()
            publish_feeds()
            log_sdcard()
            if gc:
                pass
                # rotate_pumps()



if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for p in pumps:
            p.throttle = 0
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
