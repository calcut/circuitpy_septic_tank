
from adafruit_motor.motor import DCMotor
import adafruit_logging as logging

import digitalio
import time

class Valve():

    def __init__(self, motor:DCMotor, name, loghandler=None):
        self.motor = motor
        self.name = name

        # For valves that need to be actively closed, add another motor driver
        self.motor_close = None

        self.manual = False
        self.pulsing = False

        self.pulses = 24
        self.timer_toggle = -1000

        self.open_duration = 10
        self.close_duration = 120

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
                self.log.info(f'closed in {round(time.monotonic() - self.timer_close, 1)}s')

        if self.opening:
            if time.monotonic() - self.timer_open > 10:
                self.log.critical('Valve not Opened after 10s, possible blockage')
                self.opening = False
                self.blocked = True
            if self.gpio_open.value == False:
                self.opening = False
                self.blocked = False
                self.log.info(f'opened in {round(time.monotonic() - self.timer_open, 1)}s')

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
                    if time.monotonic() - self.timer_toggle > self.open_duration:
                        self.timer_toggle = time.monotonic()
                        if self.pulse >= self.pulses:
                            self.pulse = 0
                            self.pulsing = False
                        self.close()
                else:
                    if time.monotonic() - self.timer_toggle > self.close_duration:
                        self.timer_toggle = time.monotonic()
                        self.open()
                        self.pulse += 1
      
            else:
                if self.motor.throttle == 1:
                    self.close()