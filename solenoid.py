from adafruit_motorkit import MotorKit
from adafruit_motor.motor import DCMotor
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog
from circuitpy_mcu.mcu import Mcu
import supervisor

import board
import digitalio

import time

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import microcontroller
import adafruit_logging as logging

__version__ = "2.0.0.rc1"
__filename__ = "simpletest.py"
__repo__ = "https://github.com/calcut/circuitpy-septic-tank"


# global variable so valves can be shut down after keyboard interrupt
valves = []
NUM_VALVES = 2
TOGGLE_DURATION = 5 #seconds
TOGGLE_OPEN_DURATION = 10
TOGGLE_CLOSE_DURATION = 20
FLOW_INTERVAL= 6 #(0.0333= 2 minutes) hours until next pulse time
NUM_PULSES = 6
AIO_GROUP = 'boness-valve'
# LOGLEVEL = logging.DEBUG
LOGLEVEL = logging.INFO
FORCE_WIFI = False

# If separate motor driver required to close valve
CLOSING_MOTORS= True

class Valve():

    def __init__(self, motor:DCMotor, name, loghandler=None):
        self.motor = motor
        self.name = name

        # For valves that need to be actively closed, add another motor driver
        self.motor_close = None

        self.manual = False
        self.pulsing = False
        self.toggle_duration = TOGGLE_DURATION
        # self.num_pulses = NUM_PULSES
        self.timer_toggle = time.monotonic()
        self.pulse = 0

        self.manual_pos = False #closed

        self.gpio_open = None
        self.gpio_close = None

        self.timer_close = 0
        self.timer_open = 0
        self.opening = False
        self.closing = False
        self.blocked = False

        # Set up logging
        self.log = logging.getLogger(self.name)
        if loghandler:
            self.log.addHandler(loghandler)

        self.close()

    def setup_position_signals(self, pin_open=None, pin_close=None):
        if pin_open:
            self.gpio_open = digitalio.DigitalInOut(pin_open)
            self.gpio_open.switch_to_input(pull=digitalio.Pull.UP)

        if pin_close:
            self.gpio_close = digitalio.DigitalInOut(pin_close)
            self.gpio_close.switch_to_input(pull=digitalio.Pull.UP)

    def check_position(self):
        if self.motor.throttle == 1 and self.gpio_open is not None:
            if self.gpio_open.value == False:
                self.log.info('fully open')
                return True

        if self.motor.throttle == 0 and self.gpio_close is not None:
            if self.gpio_close.value == False:
                self.log.info('fully closed')
                return True

        self.log.info('position check failed')
        return False

    def toggle(self):
        # mcu.log.info(f'Toggling valve {index}')
        if self.motor.throttle == 1:
            self.close()
        else:
            self.open()

    def open(self):
        if self.motor_close:
            self.motor_close.throttle = 0
            time.sleep(0.1)
        self.motor.throttle = 1
        self.log.info(f'Opening Valve')
        self.timer_open = time.monotonic()
        self.closing = False
        if self.gpio_open:
            self.opening = True

    def close(self):
        self.motor.throttle = 0
        if self.motor_close:
            time.sleep(0.1)
            self.motor_close.throttle = 1
        self.log.info(f'Closing Valve')
        self.timer_close = time.monotonic()
        self.opening = False
        if self.gpio_close:
            self.closing = True

    def update(self):

        if self.closing:
            if time.monotonic() - self.timer_close > 10:
                self.log.critical('Valve not closed after 10s, possible blockage')
                self.closing = False
                self.blocked = True
            if self.gpio_close.value == False:
                self.closing = False
                self.blocked = False
                self.log.warning(f'closed in {round(time.monotonic() - self.timer_close, 1)}s')

        if self.opening:
            if time.monotonic() - self.timer_open > 10:
                self.log.critical('Valve not Opened after 10s, possible blockage')
                self.opening = False
                self.blocked = True
            if self.gpio_open.value == False:
                self.opening = False
                self.blocked = False
                self.log.warning(f'opened in {round(time.monotonic() - self.timer_open, 1)}s')

        if self.manual:
            self.pulsing = False
            if self.manual_pos == False:
                if self.motor.throttle == 1:
                    self.close()
            else:
                if self.motor.throttle == 0:
                    self.open()

        else: #Auto/Scheduled mode
            if self.pulsing:
                if self.motor.throttle == 1:

                    if time.monotonic() - self.timer_toggle > TOGGLE_OPEN_DURATION:
                        self.timer_toggle = time.monotonic()

                        self.toggle()
                        self.pulse += 1

                else:
                    if time.monotonic() - self.timer_toggle > TOGGLE_CLOSE_DURATION:
                        self.timer_toggle = time.monotonic()
                        self.toggle()

                if self.pulse >= NUM_PULSES:
                    self.pulse = 0
                    self.pulsing = False
                    self.close()
      
            else:
                if self.motor.throttle == 1:
                    self.close()


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
    mcu.log.info(f'STARTING {__filename__} {__version__}')


    mcu.attach_rtc_pcf8523()

    # External I2C display
    mcu.attach_display_sparkfun_20x4()

    # Use SD card
    if mcu.attach_sdcard():
        if supervisor.runtime.usb_connected:
            print('USB connected, deleting archive files')
            mcu.delete_archive()
        mcu.archive_file('log.txt')


    wifi = True
    wifi_switch = digitalio.DigitalInOut(board.A5)
    wifi_switch.switch_to_input(digitalio.Pull.UP)

    if FORCE_WIFI:
        wifi = True

    elif wifi_switch.value == True:
        mcu.log.warning('wifi_switch board.A5 pulled up, disabling wifi')
        wifi = False

    if wifi:
        # Networking Setup
        mcu.wifi.connect()

        # Decide how to handle offline periods 
        mcu.wifi.offline_retry_connection =  60 #retry every 60 seconds, default
        # mcu.wifi.offline_retry_connection =  False #Hard reset

        if mcu.aio_setup(aio_group=f'{AIO_GROUP}-{mcu.id}'):
            mcu.aio.subscribe('led-color')
            mcu.aio.subscribe('flow-interval')
            mcu.aio.subscribe('next-flow')
            mcu.aio.subscribe('toggle-open-duration')
            mcu.aio.subscribe('toggle-close-duration')
            mcu.aio.subscribe('pulses')

    try:
        global valves
        valve_driver = MotorKit(i2c=mcu.i2c, address=0x78)

        if CLOSING_MOTORS:
            mcu.log.warning('Using "Closing Motors" for double driven valves')
            motors = [valve_driver.motor1, valve_driver.motor3]
        else:
            motors = [valve_driver.motor1, valve_driver.motor2, valve_driver.motor3, valve_driver.motor4]

        # Drop any unused valves as defined by the NUM_VALVES parameter
        motors = motors[:NUM_VALVES]
        valves = []
        
        i=0
        for m in motors:
            i+=1
            valves.append(Valve(motor=m, name=f'v{i:02}', loghandler=mcu.loghandler))
            if mcu.aio:
                mcu.aio.subscribe(f"v{i:02}-mode")
                mcu.aio.subscribe(f"v{i:02}-manual-pos")

        if CLOSING_MOTORS:
            valves[0].motor_close = valve_driver.motor2
            valves[0].close()
            valves[0].setup_position_signals(pin_open=board.D9, pin_close=board.D11)
            valves[1].motor_close = valve_driver.motor4
            valves[1].close()
        
    except Exception as e:
        mcu.handle_exception(e)
        mcu.log.warning('valve driver not found')


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

    def set_alarm(hour=0, minute=1, repeat="daily"):
        # NB setting alarm seconds is not supported by the hardware
        alarm_time = time.struct_time((2000,1,1,hour,minute,0,0,1,-1))
        mcu.rtc.alarm = (alarm_time, repeat)
        mcu.log.warning(f"alarm set for {alarm_time.tm_hour:02d}:{alarm_time.tm_min:02d}:00")
        if mcu.aio:
            mcu.aio.publish(feed_key='next-flow', data=f'{alarm_time.tm_hour:02}:{alarm_time.tm_min:02}')

    def set_countdown_alarm(hours=0, minutes=0, repeat="daily"):
        # NB setting alarm seconds is not supported by the hardware
        posix_time = time.mktime(mcu.rtc.datetime)
        alarm_time = time.localtime(posix_time + int(minutes*60) + int(hours*60*60))
        mcu.rtc.alarm = (alarm_time, repeat)
        mcu.log.warning(f"alarm set for {alarm_time.tm_hour:02d}:{alarm_time.tm_min:02d}:00")
        if mcu.aio:
            mcu.aio.publish(feed_key='next-flow', data=f'{alarm_time.tm_hour:02}:{alarm_time.tm_min:02}')

    def parse_feeds():
        try:
            for feed_id in mcu.aio.updated_feeds.keys():
                payload = mcu.aio.updated_feeds.pop(feed_id)
                mcu.log.debug(f"Got MQTT Command {feed_id=}, {payload=}")

                if feed_id == 'toggle-open-duration':
                    global TOGGLE_OPEN_DURATION
                    TOGGLE_OPEN_DURATION = float(payload)
                    mcu.log.info(f'setting {TOGGLE_OPEN_DURATION=}')

                elif feed_id == 'toggle-close-duration':
                    global TOGGLE_CLOSE_DURATION
                    TOGGLE_CLOSE_DURATION = float(payload)
                    mcu.log.info(f'setting {TOGGLE_CLOSE_DURATION=}')
                    
                elif feed_id == 'pulses':
                    global NUM_PULSES
                    NUM_PULSES = int(payload)
                    mcu.log.info(f'setting {NUM_PULSES=}')

                elif feed_id == 'flow-interval':
                    global FLOW_INTERVAL
                    FLOW_INTERVAL = float(payload)
                    mcu.log.info(f'setting {FLOW_INTERVAL=}')

                elif feed_id == 'next-flow':
                        nf = payload.split(':')
                        if len(nf) == 2:
                            hour = int(nf[0])
                            minute = int(nf[1])
                            a = mcu.rtc.alarm[0]

                            # only update if there is a change
                            if (hour != a.tm_hour) or (minute != a.tm_min):
                                set_alarm(hour, minute)
                        else:
                            mcu.log.error(f"Couldn't parse next-flow {payload}")

                elif feed_id[0] == 'v' and feed_id[3] == '-':
                    valve_index = int(feed_id[1:3])
                    category = feed_id[4:]

                    if category == 'mode':
                        if payload == 'Auto':
                            valves[valve_index-1].manual = False
                        else:
                            valves[valve_index-1].manual = True

                    elif category == 'manual-pos':
                        if payload == 'Open':
                            valves[valve_index-1].manual_pos = True
                        else:
                            valves[valve_index-1].manual_pos = False


                elif feed_id == 'led-color':
                    mcu.pixel[0] = int(payload[1:], 16)

                elif feed_id == 'ota':
                    mcu.ota_reboot()

        except Exception as e:
            mcu.handle_exception(e)

    def display():

        status = ''
        for v in valves:

            if v.blocked:
                s = '*'
            # elif v.closing == True:
            #     s = 'C'
            # elif v.opening == True:
            #     s = 'O'
            elif v.motor.throttle == 1:
                s = '1'
            else:
                s = '0'
            status += f'{s} '

        mcu.display.set_cursor(0,0)
        mcu.display.write(mcu.get_timestamp()[:20])
        mcu.display.set_cursor(0,1)
        a = mcu.rtc.alarm[0]
        mcu.display.write(f'Next Flow: {a.tm_hour:02}:{a.tm_min:02}:{a.tm_sec:02}'[:20])
        mcu.display.set_cursor(0,2)
        mcu.display.write(status)
        mcu.display.set_cursor(0,3)
        mcu.display.write(f'Pulse {valves[0].pulse}/{NUM_PULSES}')

        try:
            if status != mcu.valve_status:
                mcu.log.info(f'Valves: {status} Pulse {valves[0].pulse}/{NUM_PULSES}' )
        except AttributeError:
            pass
        mcu.valve_status = status

    timer_A = 0
    timer_networking = 0

    if mcu.aio is None:
        # set_countdown_alarm(hours=FLOW_INTERVAL)
        set_alarm(hour=9, minute=0)

    mcu.booting = False # Stop accumulating boot log messages
    if mcu.aio is not None:
        mcu.aio.publish_long('log', mcu.logdata) # Send the boot log


    while True:
        mcu.service(serial_parser=usb_serial_parser)
        for v in valves:
            v.update()

        if mcu.rtc.alarm_status:
            mcu.log.warning('RTC Alarm: Flow Starting')
            mcu.rtc.alarm_status = False

            for v in valves:
                v.pulsing = True
            set_countdown_alarm(hours=FLOW_INTERVAL)

        if time.monotonic() - timer_A > 1:
            timer_A = time.monotonic()
            mcu.led.value = not mcu.led.value #heartbeat LED
            display()


        if wifi:
            if time.monotonic() - timer_networking > 1:
                timer_networking = time.monotonic()
                timestamp = mcu.get_timestamp()
                mcu.data['debug'] = timestamp

                active = False
                for v in valves:
                    if v.pulsing:
                        active = True
                # This prevents trying to reconnect while valve is active/toggling
                if active and not mcu.wifi.connected:
                    pass
                else:
                    mcu.aio_sync(mcu.data, publish_interval=60)
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
