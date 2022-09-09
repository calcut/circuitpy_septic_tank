from adafruit_motorkit import MotorKit
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_mcu.mcu import Mcu

import time

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import microcontroller
import adafruit_logging as logging


# global variable so valves can be shut down after keyboard interrupt
valves = []
NUM_VALVES = 1
TOGGLE_DURATION = 5 #seconds
VALVE_INACTIVE_TIME= 1 #minute
VALVE_ACTIVE_TIME = 1 #minute
AIO_GROUP = 'boness-valve'
LOGLEVEL = logging.DEBUG
# LOGLEVEL = logging.INFO

def main():

    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        '0x68' : 'Realtime Clock PCF8523', # On Adalogger Featherwing
        '0x78' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A4 and A3
        '0x72' : 'Sparkfun LCD Display',
        '0x77' : 'Temp/Humidity/Pressure BME280' # Built into some ESP32S2 feathers 
    }

    mcu = Mcu(loglevel=LOGLEVEL)
    mcu.booting = True # A flag to record boot messages

    mcu.attach_rtc_pcf8523()

    # Use SD card
    if mcu.attach_sdcard():
        mcu.delete_archive()
        mcu.archive_file('log.txt')

    # Networking Setup
    mcu.wifi.connect()

    # Decide how to handle offline periods 
    mcu.wifi.offline_retry_connection =  60 #retry every 60 seconds, default
    # mcu.wifi.offline_retry_connection =  False #Hard reset

    if mcu.aio_setup(aio_group=f'{AIO_GROUP}-{mcu.id}'):
        mcu.aio.connect()
        mcu.aio.subscribe('led-color')
        mcu.aio.subscribe('active-minutes')
        mcu.aio.subscribe('inactive-minutes')

    try:
        global valves
        valve_driver = MotorKit(i2c=mcu.i2c, address=0x78)
        valves = [valve_driver.motor1, valve_driver.motor2, valve_driver.motor3, valve_driver.motor4]

        # Drop any unused valves as defined by the NUM_VALVES parameter
        valves = valves[:NUM_VALVES]
        
    except Exception as e:
        mcu.handle_exception(e)
        mcu.log.warning('valve driver not found')


    def toggle_valve(index):
        global valves
        # mcu.log.info(f'Toggling valve {index}')
        if valves[index].throttle == 1:
            close_valve(index)
        else:
            open_valve(index)

    def open_valve(index):
        global valves
        valves[index].throttle = 1
        mcu.log.info(f'Opening Valve {index}')

    def close_valve(index):
        global valves
        valves[index].throttle = 0
        mcu.log.info(f'Closing Valve {index}')


    def usb_serial_parser(string):
        global valves

        if string.startswith('v'):
            try:
                index = int(string[1])
                toggle_valve(index)

            except Exception as e:
                print(e)
                mcu.log.warning(f'string {string} not valid for valve settings\n'
                                 +'input valve settings in format "v valve_number" e.g. v0')

    def set_alarm(hour=0, minute=1, repeat="daily"):
        # NB setting alarm seconds is not supported by the hardware
        alarm_time = time.struct_time((2000,1,1,hour,minute,0,0,19,-1))
        mcu.rtc.alarm = (alarm_time, repeat)
        mcu.log.info(f"alarm set for {alarm_time.tm_hour:02d}:{alarm_time.tm_min:02d}:00")

    def set_countdown_alarm(hours=0, minutes=1, repeat="daily"):
        # NB setting alarm seconds is not supported by the hardware
        posix_time = time.mktime(mcu.rtc.datetime)
        alarm_time = time.localtime(posix_time + minutes*60 + hours*60*60)
        mcu.rtc.alarm = (alarm_time, repeat)
        mcu.log.info(f"alarm set for {alarm_time.tm_hour:02d}:{alarm_time.tm_min:02d}:00")

    def parse_feeds():
        try:
            for feed_id in mcu.aio.updated_feeds.keys():
                payload = mcu.aio.updated_feeds.pop(feed_id)

                if feed_id == 'active-minutes':
                    global VALVE_ACTIVE_TIME
                    VALVE_ACTIVE_TIME = int(payload)

                if feed_id == 'inactive-minutes':
                    global VALVE_INACTIVE_TIME
                    VALVE_INACTIVE_TIME = int(payload)

                if feed_id == 'led-color':
                    mcu.pixel[0] = int(payload[1:], 16)

                if feed_id == 'ota':
                    mcu.ota_reboot()

        except Exception as e:
            mcu.handle_exception(e)

    timer_A = 0
    timer_networking = 0
    timer_toggle=0
    valve_active = True
    set_countdown_alarm(minutes=VALVE_ACTIVE_TIME)

    while True:
        mcu.service(serial_parser=usb_serial_parser)
        microcontroller.watchdog.feed()

        if time.monotonic() - timer_networking > 1:
            timer_networking = time.monotonic()
            mcu.led.value = not mcu.led.value #heartbeat LED
            timestamp = mcu.get_timestamp()
            mcu.data['debug'] = timestamp
            if valve_active and not mcu.wifi.connected:
                # This prevents trying to reconnect while valve is active/toggling
                pass
            else:
                mcu.aio_sync(mcu.data)
                parse_feeds()

        # Decide whether valve should be active or not
        if time.monotonic() - timer_A > 1:
            if mcu.rtc.alarm_status:
                mcu.log.info('RTC Alarm detected')
                mcu.rtc.alarm_status = False

                if valve_active:
                    valve_active = False
                    for v in valves:
                        v.throttle = 0
                    set_countdown_alarm(minutes=VALVE_INACTIVE_TIME)
                else:
                    valve_active = True
                    set_countdown_alarm(minutes=VALVE_ACTIVE_TIME)  

        if valve_active:
            if time.monotonic() - timer_toggle > TOGGLE_DURATION:
                timer_toggle = time.monotonic()
                toggle_valve(0)


if __name__ == "__main__":
    try:
        enable_watchdog(timeout=60)
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for v in valves:
            v.throttle = 0

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        reset(e)