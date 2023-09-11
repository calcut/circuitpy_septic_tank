import time
from circuitpy_mcu.mcu import Mcu
from circuitpy_mcu.notecard_manager import Notecard_manager
from circuitpy_mcu.ota_bootloader import reset, enable_watchdog

import busio
import board
import digitalio

# scheduling and event/error handling libs
import adafruit_logging as logging


__version__ = "3.4.2"
__repo__ = "https://github.com/calcut/circuitpy-septic_tank"
__filename__ = "septic_tank.py"


MINUTES = 60
# MINUTES = 1

# LOGLEVEL = logging.INFO
LOGLEVEL = logging.DEBUG

# DELETE_ARCHIVE = False
DELETE_ARCHIVE = True



def main():

    # set defaults for environment variables, (may be overridden by notehub)
    env = {
        'pump1-speed'           : 0.6,
        'pump2-speed'           : 0.6,
        'pump3-speed'           : 0.6,
        'pump4-speed'           : 0.6,
        'jacket-target-temps'   : [30, 30, 30],
        'jacket-hysteresis'     : 0.5,
        'jacket-control'        : True,
        'gascard'               : True,
        'ph-temp-interval'      : 1, #minutes
        'note-send-interval'    : 1, #minutes
        'gc-sample-times'       : ["02:00", "06:00", "10:00", "14:00", "18:00", "22:00"],
        'utc-offset-hours'      : 1,
        'gc-pump-time'          : 240,# 4 minutes
        'gc-pump-sequence'      : [1, 4, 2, 4, 3, 4],
        'gc-pressure-settling'  : 10,
        'num-pumps'             : 4,
        'ph-channels'           : 3,
        'dispay-page-time'      : 8, #seconds
        'ota'                   : __version__
        }


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
        '0x62' : 'Thermocouple Amp MCP9600',
        '0x63' : 'Thermocouple Amp MCP9600',
        '0x64' : 'Thermocouple Amp MCP9600',
        '0x65' : 'Thermocouple Amp MCP9600',
        '0x66' : 'Thermocouple Amp MCP9600',
        '0x67' : 'Thermocouple Amp MCP9600',
        '0x6E' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A1 A2 A3
        '0x6F' : 'Motor Featherwing PCA9685', #Solder bridge on address bit A0 A1 A2 A3
        '0x70' : 'PCA9685 (All Call)', #Combined "All Call" address (not supported)
    }

    # instantiate the MCU helper class to set up the system
    mcu = Mcu(loglevel=LOGLEVEL, i2c_freq=100000)
    

    ncm = Notecard_manager(loghandler=mcu.loghandler, i2c=mcu.i2c, watchdog=120, loglevel=LOGLEVEL)
    mcu.log.info(f'STARTING {__filename__} {__version__}')

    mcu.i2c_identify(i2c_dict)
    # mcu.i2c_identify(i2c2_dict, i2c=mcu.i2c2)

    mcu.log.warning(f'BOOT complete at {mcu.get_timestamp()} UTC, {mcu.get_timestamp(env["utc-offset-hours"])} local')


    timer_C=0
    timer_D=-15*MINUTES
    while True:
        mcu.service()

        if time.monotonic() - timer_C > 5:
            timer_C = time.monotonic()

            timestamp = mcu.get_timestamp(env['utc-offset-hours'])
            mcu.log.debug(f"servicing notecard now {timestamp}")

            # Checks if connected, storage availablity, etc.
            ncm.check_status(nosync_timeout=600)
            if ncm.connected:
                mcu.pixel[0] = mcu.pixel.MAGENTA
            else:
                mcu.pixel[0] = mcu.pixel.RED

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

    except Exception as e:
        print(f'Code stopped by unhandled exception:')
        reset(e)
