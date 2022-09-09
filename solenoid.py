from adafruit_motorkit import MotorKit
from adafruit_motor.motor import DCMotor
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_mcu.mcu import Mcu

import time

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import microcontroller
import adafruit_logging as logging


# global variable so valves can be shut down after keyboard interrupt
valves = []
NUM_VALVES = 4
TOGGLE_DURATION = 5 #seconds
VALVE_PERIOD= 2 #minutes until next active time
VALVE_ACTIVE_DURATION = 1 #minute
NUM_BURSTS = 6
AIO_GROUP = 'boness-valve'
# LOGLEVEL = logging.DEBUG
LOGLEVEL = logging.INFO
WIFI = False

class Valve():

    def __init__(self, motor:DCMotor, name, loghandler=None):
        self.motor = motor
        self.motor.throttle = 0
        self.name = name

        self.active = False
        self.toggle_duration = TOGGLE_DURATION
        self.num_bursts = NUM_BURSTS
        self.timer_toggle = time.monotonic()
        self.timer_active = time.monotonic()
        self.burst = 0

        # Set up logging
        self.log = logging.getLogger(self.name)
        if loghandler:
            self.log.addHandler(loghandler)

    def toggle(self):
        # mcu.log.info(f'Toggling valve {index}')
        if self.motor.throttle == 1:
            self.close()
        else:
            self.open()

    def open(self):
        self.motor.throttle = 1
        self.log.info(f'Opening Valve')

    def close(self):
        self.motor.throttle = 0
        self.log.info(f'Closing Valve')

    def display(self, message):
        # Special log command with custom level, to request sending to attached display
        self.log.log(level=25, msg=message)

    def set_active(self):
        self.active = True
        self.timer_active = time.monotonic()

    def update(self):
        if self.active:
            if self.burst >= self.num_bursts:
                self.burst = 0
                self.active = False
                self.close()

            elif time.monotonic() - self.timer_toggle > TOGGLE_DURATION:
                self.timer_toggle = time.monotonic()
                self.toggle()
                if self.motor.throttle == 1:
                    self.burst += 1



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

    # External I2C display
    mcu.attach_display_sparkfun_20x4()

    # Use SD card
    if mcu.attach_sdcard():
        mcu.delete_archive()
        mcu.archive_file('log.txt')

    if WIFI:
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
        motors = [valve_driver.motor1, valve_driver.motor2, valve_driver.motor3, valve_driver.motor4]

        # Drop any unused valves as defined by the NUM_VALVES parameter
        motors = motors[:NUM_VALVES]
        valves = []
        
        i=0
        for m in motors:
            i+=1
            valves.append(Valve(motor=m, name=f'V{i}', loghandler=mcu.loghandler))
        
    except Exception as e:
        mcu.handle_exception(e)
        mcu.log.warning('valve driver not found')


    def usb_serial_parser(string):
        global valves

        if string.startswith('v'):
            try:
                index = int(string[1])
                valves[index].toggle()

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

    def display():

        status = ''
        for v in valves:
            if v.active:
                if v.motor.throttle == 1:
                    s = '1'
                else:
                    s = '0'
            else:
                s = 'X'
            status += f'{s} '

        mcu.display.set_cursor(0,0)
        mcu.display.write(mcu.get_timestamp()[:20])
        mcu.display.set_cursor(0,1)
        a = mcu.rtc.alarm[0]
        mcu.display.write(f'Next Flow: {a.tm_hour:02}:{a.tm_min:02}:{a.tm_sec:02}'[:20])
        mcu.display.set_cursor(0,2)
        mcu.display.write(status)
        mcu.display.set_cursor(0,3)
        mcu.display.write(f'Burst {valves[0].burst}/{valves[0].num_bursts}')

    timer_A = 0
    timer_networking = 0
    set_countdown_alarm(minutes=VALVE_PERIOD)
    for v in valves:
        v.set_active()

    while True:
        mcu.service(serial_parser=usb_serial_parser)


        if mcu.rtc.alarm_status:
            mcu.log.info('RTC Alarm detected')
            mcu.rtc.alarm_status = False

            for v in valves:
                v.set_active()
            mcu.display_text('Valves Active')
            set_countdown_alarm(minutes=VALVE_PERIOD)


        # Update Valves
        if time.monotonic() - timer_A > 1:
            timer_A = time.monotonic()
            mcu.led.value = not mcu.led.value #heartbeat LED
            display()
            for v in valves:
                v.update()

        if WIFI:
            if time.monotonic() - timer_networking > 1:
                timer_networking = time.monotonic()
                timestamp = mcu.get_timestamp()
                mcu.data['debug'] = timestamp

                # This prevents trying to reconnect while valve is active/toggling
                active = False
                for v in valves:
                    if v.active:
                        active = True
                if active and not mcu.wifi.connected:
                    
                    pass
                else:
                    mcu.aio_sync(mcu.data)
                    parse_feeds()


if __name__ == "__main__":
    try:
        enable_watchdog(timeout=60)
        main()
    except KeyboardInterrupt:
        print('Code Stopped by Keyboard Interrupt')
        for v in valves:
            v.close()

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        reset(e)