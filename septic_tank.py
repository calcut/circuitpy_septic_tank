import time
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.notecard_manager import Notecard_manager
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_septic_tank.gascard import Gascard
from circuitpy_mcu.DFRobot_PH import DFRobot_PH
import adafruit_mcp9600
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_motorkit import MotorKit
import busio
import board
import digitalio

# scheduling and event/error handling libs
import adafruit_logging as logging


__version__ = "3.1.1"
__repo__ = "https://github.com/calcut/circuitpy-septic_tank"
__filename__ = "septic_tank.py"


MINUTES = 60
# MINUTES = 1

# LOGLEVEL = logging.INFO
LOGLEVEL = logging.DEBUG

# DELETE_ARCHIVE = False
DELETE_ARCHIVE = True

PIN_JACKET1 = board.D9
PIN_JACKET2 = board.D11
PIN_JACKET3 = board.D12

# global variable so pumps can be shut down after keyboard interrupt
pumps_in = []
pumps_out = []

def main():

    # set defaults for environment variables, (may be overridden by notehub)
    env = {
        'pump1-speed'           : 0.6,
        'pump2-speed'           : 0.6,
        'pump3-speed'           : 0.6,
        'pump4-speed'           : 0.6,
        'jacket-target-temps'   : [30, 30, 30],
        'jacket-hysteresis'     : 0.5,
        'gascard'               : True,
        'ph-temp-interval'      : 1, #minutes
        'note-send-interval'    : 30, #minutes
        'gc-sample-times'       : ["02:00", "06:00", "10:00", "14:00", "18:00", "22:00"],
        'gc-pump-time'          : 240,# 4 minutes
        'gc-pump-sequence'      : [1, 4, 2, 4, 3, 4],
        'num-pumps'             : 4,
        'ph-channels'           : 3,
        'dispay-page-time'      : 8, #seconds
        'ota'                   : __version__
        }

    def parse_environment():

        nonlocal next_gc_sample
        nonlocal timer_gc_sample
        nonlocal next_gc_sample_countdown

        for key, val in env.items():

            if key == 'led-color':
                r = int(val[1:3], 16)
                g = int(val[3:5], 16)
                b = int(val[5:], 16)
                mcu.display.set_fast_backlight_rgb(r, g, b)

            if key == 'gc-sample-times':
                timer_gc_sample = time.monotonic()
                next_gc_sample_countdown = mcu.get_next_alarm(val)
                next_gc_sample = time.localtime(time.time() + next_gc_sample_countdown)
                mcu.log.warning(f"alarm set for {next_gc_sample.tm_hour:02d}:{next_gc_sample.tm_min:02d}:00")

            if key == 'ota':
                if val == __version__:
                    mcu.log.info(f"Not performing OTA, version matches {val}")
                else:
                    for p in pumps_in:
                        p.throttle = 0
                    for p in pumps_out:
                        p.throttle = 0
                    mcu.ota_reboot()

    pump_index = 1 # track which pump is active
    gc_sequence_index = 0 #track position in the gc_pump_sequence list

    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x17' : 'BluesWireless Notecard', 
        '0x68' : 'Realtime Clock PCF8523', # On Adalogger Featherwing
        '0x72' : 'Sparkfun LCD Display',
        # '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    i2c2_dict = {
        '0x48' : 'ADC for pH Probes ADC1115',
        '0x60' : 'Thermocouple Amp MCP9600',
        '0x61' : 'Thermocouple Amp MCP9600',
        # '0x62' : 'Thermocouple Amp MCP9600',
        # '0x63' : 'Thermocouple Amp MCP9600',
        '0x64' : 'Thermocouple Amp MCP9600',
        '0x65' : 'Thermocouple Amp MCP9600',
        '0x66' : 'Thermocouple Amp MCP9600',
        '0x67' : 'Thermocouple Amp MCP9600',
        '0x6E' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A1 A2 A3
        '0x6F' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A0 A1 A2 A3
        '0x70' : 'PCA9685 (All Call)', #Combined "All Call" address (not supported)
    }

    timer_pump = 999999 #controls when gc pumps stop. initialised large, to avoid early sampling
    timer_capture = time.monotonic() # controls general sample interval
    timer_gc_sample = time.monotonic() #controls when gc pumps start
    next_gc_sample = None
    next_gc_sample_countdown = 0
    gc_sample_memory = { # For displaying historical/previous samples
        "gc1" : None,
        "gc2" : None,
        "gc3" : None,
    }
    display_page = 0
    timer_display_page = time.monotonic()

    # instantiate the MCU helper class to set up the system
    mcu = Mcu(loglevel=LOGLEVEL, i2c_freq=100000)
    mcu.enable_i2c2()
    
    # Check what devices are present on the i2c bus
    mcu.i2c_identify(i2c_dict)
    mcu.i2c_identify(i2c2_dict, i2c=mcu.i2c2)
    mcu.attach_display_sparkfun_20x4()

    ncm = Notecard_manager(loghandler=mcu.loghandler, i2c=mcu.i2c, watchdog=120, loglevel=LOGLEVEL)
    mcu.log.info(f'STARTING {__filename__} {__version__}')

    ncm.set_default_envs(env)
    parse_environment()

    def connect_thermocouple_channels():
        tc_addresses = [0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67]
        tc_channels = []

        for addr in tc_addresses:
            try:
                tc = adafruit_mcp9600.MCP9600(mcu.i2c2, address=addr)
                tc_channels.append(tc)
                mcu.log.info(f'Found thermocouple channel at address {addr:x}')
                
            except Exception as e:
                mcu.log.info(f'No thermocouple channel at {addr:x}')

        return tc_channels

    def connect_jacket_relays():
        jacket_relays = []

        try:
            j1 = digitalio.DigitalInOut(PIN_JACKET1)
            j1.direction = digitalio.Direction.OUTPUT
            j1.value = True
            jacket_relays.append(j1)

            j2 = digitalio.DigitalInOut(PIN_JACKET2)
            j2.direction = digitalio.Direction.OUTPUT
            j2.value = False
            jacket_relays.append(j2)

            j3 = digitalio.DigitalInOut(PIN_JACKET3)
            j3.direction = digitalio.Direction.OUTPUT
            j3.value = False
            jacket_relays.append(j3)

        except Exception as e:
            mcu.log.info(f"error connecting jacket relays {e}")

        return jacket_relays

    def connect_ph_channels():
        try:
            ph_channels = []
            ads = ADS.ADS1115(mcu.i2c2)
            adc_list = [ADS.P0, ADS.P1, ADS.P2, ADS.P3]

            # Drop any unwanted/unused channels, as specified by ph-channels environment variable
            adc_list = adc_list[:env['ph-channels']] 

            for ch in adc_list:
                ph_channel = DFRobot_PH(
                    analog_in = AnalogIn(ads, ch),
                    calibration_file= f'/calibration/ph_calibration_ch{ch+1}.txt',
                    log_handler = mcu.loghandler
                    )
                ph_channels.append(ph_channel)

        except Exception as e:
            mcu.handle_exception(e)
            mcu.log.info('ADC for pH probes not found')

        return ph_channels


    def connect_pumps():
        try:
            global pumps_in
            global pumps_out
            # Changing pwm freq from 1600Hz to <500Hz helps a lot with matching speeds. unsure exactly why. 
            pump_driver_out = MotorKit(i2c=mcu.i2c2, address=0x6E, pwm_frequency=400)
            pump_driver_in = MotorKit(i2c=mcu.i2c2, address=0x6F, pwm_frequency=400)
            pumps_in = [pump_driver_in.motor1, pump_driver_in.motor2, pump_driver_in.motor3, pump_driver_in.motor4]
            pumps_out = [pump_driver_out.motor1, pump_driver_out.motor2, pump_driver_out.motor3, pump_driver_out.motor4]

            # Drop any unused pumps as defined by the num-pumps environment variable
            pumps_in = pumps_in[:env['num-pumps']]
            pumps_out = pumps_out[:env['num-pumps']]

            for p in pumps_in:
                p.throttle = 0
            for p in pumps_out:
                p.throttle = 0
            
        except Exception as e:
            mcu.handle_exception(e)
            mcu.log.warning('Pump driver not found')
        
        # return pumps_in

    def connect_gascard():
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

        return gc


    tc_channels = connect_thermocouple_channels()
    jacket_relays = connect_jacket_relays()
    ph_channels = connect_ph_channels()
    connect_pumps()

    if mcu.display:
        mcu.display.clear()
        mcu.display.write(f'{len(tc_channels)} TC channels')
        mcu.display.set_cursor(0,1)
        mcu.display.write(f'{len(ph_channels)} pH channels')
        mcu.display.set_cursor(0,2)
        mcu.display.write(f'{len(pumps_in)} air pumps')
        mcu.display.set_cursor(0,3)
        mcu.display.write(f'Waiting for gascard')

    if env['gascard']:
        gc = connect_gascard()
    else:
        gc = None

    # Display gascard info
    if mcu.display:
        if gc:
            mcu.display.clear()
            mcu.display.write(f'Gascard Found')
        else:
            mcu.display.clear()
            mcu.display.write(f'Gascard not used')
        time.sleep(1)



    def capture_data(interval=1):
        nonlocal timer_capture
        nonlocal timer_pump
        nonlocal timer_gc_sample

        nonlocal next_gc_sample_countdown
        nonlocal next_gc_sample
        nonlocal gc_sequence_index
        nonlocal pump_index

        global pumps_in
        global pumps_out

        if (time.monotonic() - timer_capture) >= interval:
            timer_capture = time.monotonic()
        
            # keep keys 'url safe', i.e.
            # lower case ASCII letters, numbers, dashes only

            for ph in ph_channels:
                i = ph_channels.index(ph)
                mcu.data[f'ph{i+1}'] = ph.read_PH()
                
            for tc in tc_channels:
                i = tc_channels.index(tc)
                mcu.data[f'tc{i+1}'] = tc.temperature

            if gc:
                mcu.data[f'debug-concentration'] = gc.concentration * 100

        if len(pumps_in) > 0:
            if time.monotonic() - timer_gc_sample > next_gc_sample_countdown:
                timer_gc_sample = time.monotonic()
                next_gc_sample_countdown = mcu.get_next_alarm(env['gc-sample-times'])
                next_gc_sample = time.localtime(time.time() + next_gc_sample_countdown)
                mcu.log.warning(f"alarm set for {next_gc_sample.tm_hour:02d}:{next_gc_sample.tm_min:02d}:00")

                pump_index = env['gc-pump-sequence'][gc_sequence_index]
                speed = env[f'pump{pump_index}-speed']
                pumps_in[pump_index-1].throttle = speed
                pumps_out[pump_index-1].throttle = speed
                timer_pump = time.monotonic()
                mcu.log.info(f'GC sampling sequence: Starting with pump {pump_index} at {speed=}')

            if time.monotonic() - timer_pump > env['gc-pump-time']:
                print(f'{timer_pump=}')

                if gc:
                    sample = gc.concentration * 100
                    mcu.data[f'gc{pump_index}'] = sample
                    gc_sample_memory[f'gc{pump_index}'] = sample
                    mcu.log.info(f'Capturing gascard gc{pump_index} sample')

                pumps_in[pump_index-1].throttle = 0
                pumps_out[pump_index-1].throttle = 0  
                mcu.log.info(f'disabling pump{pump_index} after {env["gc-pump-time"]}s')

                gc_sequence_index += 1
                if gc_sequence_index >= len(env['gc-pump-sequence']) :
                    gc_sequence_index = 0
                    # Push timer_pump out into the future so this won't trigger again until after the next sample alarm
                    timer_pump = time.monotonic() + 99999
                    mcu.log.info(f'GC sampling sequence complete')

                else:
                    pump_index = env['gc-pump-sequence'][gc_sequence_index]
                    speed = env[f'pump{pump_index}-speed']
                    pumps_in[pump_index-1].throttle = speed
                    pumps_out[pump_index-1].throttle = speed
                    timer_pump = time.monotonic()
                    mcu.log.info(f'GC sampling sequence: running pump {pump_index} at {speed=}')

        display_summary()

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
        nonlocal next_gc_sample
        nonlocal display_page
        nonlocal timer_display_page

        if time.monotonic() - timer_display_page > env['dispay-page-time']:
            timer_display_page = time.monotonic()
            if display_page == 1:
                display_page = 0
            else:
                display_page += 1

        try:
            if mcu.display:
                if display_page == 0:
                    mcu.display.set_cursor(0,0)
                    line = 'gc'
                    for key in sorted(gc_sample_memory):
                        # display as float with max 4 decimal places, and max 7 chars long
                        value = gc_sample_memory[key]
                        if value is not None:
                            line += f' {value:3.2f}'
                        else:
                            line += f' None'
                    mcu.display.write(f"{line:<20}"[:20])

                    lineA = 'tA'
                    lineB = 'tB'
                    data = filter_data('tc', decimal_places=1)
                    data.pop('tc7', None) # Remove the ambient temperature thermocouple if it exists
                    for key in sorted(data):
                        if (int(key[-1]) % 2) == 0:
                            lineA += f' {data[key]:3.1f}'
                        else:
                            lineB += f' {data[key]:3.1f}'

                    mcu.display.set_cursor(0,1)
                    mcu.display.write(f"{lineA:<20}"[:20])
                    mcu.display.set_cursor(0,2)
                    mcu.display.write(f"{lineB:<20}"[:20])

                    mcu.display.set_cursor(0,3)
                    line = 'pH'
                    data = filter_data('ph', decimal_places=1)
                    for key in sorted(data):
                        line+= f' {data[key]:3.1f}'
                    mcu.display.write(f"{line:<20}"[:20])

                if display_page == 1:
                    mcu.display.set_cursor(0,0)
                    line = mcu.get_timestamp()
                    mcu.display.write(f"{line:<20}"[:20])

                    mcu.display.set_cursor(0,1)
                    line = f'gc {mcu.data["debug-concentration"]:3.2f} nxtsmp={next_gc_sample.tm_hour:02d}:{next_gc_sample.tm_min:02d}      ' 
                    mcu.display.write(f"{line:<20}"[:20])

                    mcu.display.set_cursor(0,2)
                    line = f'pmps'
                    for p in pumps_in:
                        line+= f' {p.throttle:3.1f}'
                    mcu.display.write(f"{line:<20}"[:20])

                    mcu.display.set_cursor(0,3)
                    line = f'jckts '
                    for j in jacket_relays:
                        if j.value == True:
                            line+="1 "
                        else:
                            line+="0 "
                    if "tc7" in mcu.data:
                        line += f"amb={mcu.data['tc7']:3.1f}"
                    mcu.display.write(f"{line:<20}"[:20])

        except Exception as e:
            mcu.log.warning(f"{e}")

    def display_gascard_reading():
        mcu.display.labels[0]='CH4 Conc='
        mcu.display.labels[1]='Pressure='
        mcu.display.values[0] = f'{gc.concentration:7.4f}%'
        mcu.display.values[1] = f'{gc.pressure:6.1f} '
        mcu.display.show_data_long()

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

    def jacket_control():
        jacket_index = 0
        hyst = env['jacket-hysteresis']

        for j in jacket_relays:
            try:
                target_temp = env['jacket-target-temps'][jacket_index]
                tc = tc_channels[jacket_index*2] #assuming 2 thermocouples per tank
                temp = tc.temperature

                if temp <= (target_temp - hyst) and j.value == False:
                    mcu.log.debug(f"Jacket{jacket_index+1} at {temp}C, target {target_temp}C, turning on jacket")
                    j.value = True

                if temp >= (target_temp + hyst) and j.value == True:
                    mcu.log.debug(f"Jacket{jacket_index+1} at {temp}C, target {target_temp}C, turning off jacket")
                    j.value = False
            except IndexError as e:
                if len(tc_channels) < 6:
                    mcu.log.info(f"Jacket control IndexError, expected 6 thermocouple channels, found {len(tc_channels)}")
                else:
                    mcu.log.info(f"Jacket control IndexError, could be due to {env['jacket-target-temps']=}")
            except Exception as e:
                mcu.log.info(f"Jacket control exception {e}")
            finally:
                jacket_index += 1

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

        # else:
            # if gc:
                # mcu.log.info(f'Writing to Gascard [{string}]')
                # gc.write_command(string)


    mcu.log.info(f'BOOT complete at {mcu.get_timestamp()} UTC')
    if mcu.display:
        mcu.display.clear()

    timer_A=0
    timer_B=0
    timer_C=0
    timer_D=-15*MINUTES
    while True:
        mcu.service(serial_parser=usb_serial_parser)
        capture_data(interval=1)

        # Check for incoming serial messages from Gascard
        if gc:
            data_string = gc.parse_serial()
            # if gc.mode != 'Normal Channel':
            #     print(data_string)

        if time.monotonic() - timer_A > 1:
            timer_A = time.monotonic()
            jacket_control()
            mcu.led.value = not mcu.led.value #heartbeat LED

        if time.monotonic() - timer_B > (env['ph-temp-interval'] * MINUTES):
            timer_B = time.monotonic()
            ncm.add_to_timestamped_note(mcu.data)
            mcu.data.pop("gc1", None)
            mcu.data.pop("gc2", None)
            mcu.data.pop("gc3", None)

        if time.monotonic() - timer_C > 5:
            timer_C = time.monotonic()

            timestamp = mcu.get_timestamp()
            mcu.log.debug(f"servicing notecard now {timestamp}")

            # check for any new inbound notes to parse
            # ncm.receive_note()
            # parse_inbound_note()

            # check for any environment variable updates to parse
            if ncm.receive_environment(env):
                parse_environment()

        if time.monotonic() - timer_D > (env['note-send-interval'] * MINUTES):
            timer_D = time.monotonic()

            # Send note infrequently (e.g. 15 mins) to minimise consumption credit usage
            ncm.send_timestamped_note(sync=True)
            ncm.send_timestamped_log(sync=True)


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
