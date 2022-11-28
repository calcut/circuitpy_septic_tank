from adafruit_motorkit import MotorKit
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.notecard_manager import Notecard_manager

from circuitpy_septic_tank.solenoid_valve import Valve

import time

# scheduling and event/error handling libs
import adafruit_logging as logging

__version__ = "3.0.0_notecard"
__filename__ = "feed_control.py"
__repo__ = "https://github.com/calcut/circuitpy-septic-tank"

# global variable so valves can be shut down after keyboard interrupt
valves = []

MINUTES = 60

LOGLEVEL = logging.DEBUG
# LOGLEVEL = logging.INFO

def main():

    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x68' : 'Realtime Clock PCF8523', # On Adalogger Featherwing
        # '0x78' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4 and A3
        '0x6F' : 'Motor Featherwing PCA9685', #Solder bridge on address bits A0, A1, A2, A3
        '0x72' : 'Sparkfun LCD Display',
        '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    env = {
        'pulses'                : 24, #number of pulses in a feed
        'valves'                : 1, # valves under control
        'feed-times'            : ["10:00", "18:00"],
        'valve-open-duration'   : 10, #seconds open in a pulse
        'valve-close-duration'  : 120, #seconds closed in a pulse
        'v01-mode'              : "auto", # or "manual"
        'v01-manual-pos'        : "closed", # or "open"
        'ota'                   : __version__
    }

    def parse_environment():
        nonlocal next_feed_countdown
        nonlocal next_feed
        nonlocal timer_feed

        for key, val in env.items():

            if key == 'pulses':
                for v in valves:
                    v.pulses = val

            if key == 'valve-close-duration':
                for v in valves:
                    v.close_duration = val

            if key == 'valve-open-duration':
                for v in valves:
                    v.open_duration = val

            if key == 'feed-times':
                timer_feed = time.monotonic()
                next_feed_countdown = mcu.get_next_alarm(val)
                next_feed = time.localtime(time.time() + next_feed_countdown)
                mcu.log.warning(f"alarm set for {next_feed.tm_hour:02d}:{next_feed.tm_min:02d}:00")

            if key[0] == 'v' and key[3] == '-':
                valve_index = int(key[1:3])
                category = key[4:]
                try:
                    if category == 'mode':
                        if val == 'auto':
                            valves[valve_index-1].manual = False
                        else:
                            valves[valve_index-1].manual = True

                    elif category == 'manual-pos':
                        if val == 'open':
                            valves[valve_index-1].manual_pos = True
                        else:
                            valves[valve_index-1].manual_pos = False
                except IndexError:
                    # May get this if valve has not been instantiated
                    mcu.log.warning(f"IndexError: Could not set {key} to {val}")

            if key == 'ota':
                if val == __version__:
                    mcu.log.info(f"Not performing OTA, version matches {val}")
                else:
                    for v in valves:
                        v.throttle = 0
                    mcu.ota_reboot()

    next_feed_countdown = 0
    next_feed = None
    timer_feed = time.monotonic()

    mcu = Mcu(loglevel=LOGLEVEL, i2c_freq=100000)
    mcu.i2c_identify(i2c_dict)
    mcu.attach_display_sparkfun_20x4()

    ncm = Notecard_manager(loghandler=mcu.loghandler, i2c=mcu.i2c, watchdog=120, loglevel=LOGLEVEL)
    mcu.log.info(f'STARTING {__filename__} {__version__}')
    ncm.set_default_envs(env)

    try:
        global valves
        valve_driver = MotorKit(i2c=mcu.i2c, address=0x6F)

        motors = [valve_driver.motor1, valve_driver.motor2, valve_driver.motor3, valve_driver.motor4]

        # Drop any unused valves as defined by the env['valves'] parameter
        motors = motors[:env['valves']]
        valves = []
        
        i=0
        for m in motors:
            i+=1
            valves.append(Valve(motor=m, name=f'v{i:02}', loghandler=mcu.loghandler))
            if mcu.aio:
                mcu.aio_subscribe(f"v{i:02}-mode")
                mcu.aio_subscribe(f"v{i:02}-manual-pos")
        
    except Exception as e:
        mcu.handle_exception(e)
        mcu.log.warning('valve driver not found')

    parse_environment()
    
    def usb_serial_parser(string):
        global valves

        if string.startswith('v'):
            try:
                index = int(string[1])
                valves[index].manual_pos = not valves[index].manual_pos
                valves[index].manual = True

            except Exception as e:
                print(e)
                mcu.log.warning(f'string {string} not valid for valve settings\n'
                                 +'input valve settings in format "v valve_number" e.g. v0')

    def display():

        status = ''
        i=0
        for v in valves:
            i+=1
            if v.blocked:
                s = '*'
            elif v.motor.throttle == 1:
                s = 1
            else:
                s = 0
            mcu.data[f'v{i:02}-status'] = s
            status += f'{s} '

        mcu.display.set_cursor(0,0)
        mcu.display.write(mcu.get_timestamp()[:20])
        mcu.display.set_cursor(0,1)
        a = next_feed
        mcu.display.write(f'Next Feed: {a.tm_hour:02}:{a.tm_min:02}:{a.tm_sec:02}            '[:20])
        mcu.display.set_cursor(0,2)
        mcu.display.write(status)
        mcu.display.set_cursor(0,3)
        mcu.display.write(f'Pulse {valves[0].pulse}/{env["pulses"]} {int(time.monotonic()-valves[0].timer_toggle)}               '[:20])

        try:
            if status != mcu.valve_status:
                mcu.log.info(f'Valves: {status} Pulse {valves[0].pulse}/{env["pulses"]}' )
                ncm.add_to_timestamped_note(mcu.data)

        except AttributeError:
            pass
        mcu.valve_status = status

    
    timer_A = 0
    timer_B = 0
    timer_C=-15*MINUTES

    while True:
        mcu.service(serial_parser=usb_serial_parser)
        for v in valves:
            v.update()

        if time.monotonic() - timer_feed > next_feed_countdown:
            timer_feed = time.monotonic()
            next_feed_countdown = mcu.get_next_alarm(env['feed-times'])

            next_feed = time.localtime(time.time() + next_feed_countdown)
            mcu.log.warning(f"alarm set for {next_feed.tm_hour:02d}:{next_feed.tm_min:02d}:00")
            
            for v in valves:
                v.pulsing = True

        if time.monotonic() - timer_A > 1:
            timer_A = time.monotonic()
            mcu.led.value = not mcu.led.value #heartbeat LED
            display()

        if time.monotonic() - timer_B > (5):
            timer_B = time.monotonic()
            timestamp = mcu.get_timestamp()
            mcu.log.debug(f"servicing notecard now {timestamp}")
            # ncm.add_to_timestamped_note(mcu.data)

            # Checks if connected, storage availablity, etc.
            ncm.check_status()
            if ncm.connected:
                mcu.pixel[0] = mcu.pixel.MAGENTA
            else:
                mcu.pixel[0] = mcu.pixel.RED

            # # check for any new inbound notes to parse
            # ncm.receive_note()
            # parse_inbound_note()

            # check for any environment variable updates to parse
            if ncm.receive_environment(env):
                parse_environment()

        if time.monotonic() - timer_C > (15 * MINUTES):
            timer_C = time.monotonic()
            # mcu.log.info('heartbeat log for debug')

            # Send note infrequently (e.g. 15 mins) to minimise consumption credit usage
            ncm.send_timestamped_note(sync=True)
            ncm.send_timestamped_log(sync=True)


if __name__ == "__main__":
    try:
        enable_watchdog(timeout=120)
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for v in valves:
            v.close()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        reset(e)
