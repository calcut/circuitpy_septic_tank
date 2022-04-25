import time
import board
from lib.circuitpy_mcu.mcu import Mcu
import digitalio
import busio

# scheduling and event/error handling libs
from watchdog import WatchDogTimeout
import supervisor
import microcontroller
import adafruit_logging as logging
import traceback

print('imported libraries')

# Set AIO = True to use Wifi and Adafruit IO connection
# secrets.py file needs to be setup appropriately
AIO = True
# AIO = False

DEMO = False

def main():


    # Optional list of expected I2C devices and addresses
    # Maybe useful for automatic configuration in future
    i2c_dict = {
        '0x0B' : 'Battery Monitor LC709203', # Built into ESP32S2 feather 
        # '0x40' : 'Temp/Humidity HTU31D',

    }

    uart = busio.UART(board.TX, board.RX, baudrate=57600)

    # instantiate the MCU helper class to set up the system
    mcu = Mcu()

    # Choose minimum logging level to process
    mcu.log.level = logging.INFO #i.e. ignore DEBUG messages

    def send_gc_command(string):
        command_bytes = bytearray(string)
        uart.write(command_bytes + bytearray('\r'))
        response = None
        i=0
        while response != command_bytes:
            response = uart.read(len(command_bytes))
            i += 1
            if i >= 5:
                print(f'warning, no acknowledgment of command {string}')
                return
        print(f'command {string} acknowledged')

    def service_serial():
        mcu.read_serial(send_to=send_gc_command)
        mcu.watchdog.feed()
        data = uart.readline()
        if data is not None:
            data_string = ''.join([chr(b) for b in data])          
            # print(data_string, end="")
            return data_string
        else:
            return None

    def restart_gascard():
        send_gc_command('X')
        send_gc_command('q')
    
    print('Restarting Gascard')
    restart_gascard()
    state='Unknown'
    # time.sleep(0.5)

    timer_A = time.monotonic()
    timer_B = time.monotonic()

    while True:
        data_string = service_serial()
        # print(f'{data_string=}', end="")

        if data_string is None:
            continue

        if data_string[0:2] == 'N ':
            state='Normal'
        elif data_string[0:2] == 'N1':
            state='Normal Channel'
        else:
            state = 'Unknown'

        if state == 'Unknown':
            if data_string:
                print(data_string, end="")

        if state == 'Normal':
            print('switching to N1 Channel Mode')
            send_gc_command('N1')

        if state == 'Normal Channel':
            data = data_string.split(' ')
            if len(data) == 7:
                sample = data[1]
                reference = data[2]
                conc = data[4]
                temperature = data[5]
                pressure = data[6]

            if time.monotonic() - timer_A > 0.1:
                timer_A = time.monotonic()
                print(f'N1 {sample=} {reference=} {conc=} {pressure=}', end='')


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
        microcontroller.reset()
