
from watchdog import WatchDogTimeout
import supervisor
import traceback

supervisor.disable_autoreload()

# If CIRCUITPY drive is writable (configured in boot.py) this will update code files over-the-air
from circuitpy_mcu.ota_bootloader import Bootloader, reset, enable_watchdog
url = 'https://raw.githubusercontent.com/calcut/circuitpy_septic_tank/main/ota_list.py'

enable_watchdog(timeout=120)
bl = Bootloader(url)

from circuitpy_septic_tank.septic_tank import main
# from circuitpy_mcu.adafruit_io_http_test import main

try:
    main()
except KeyboardInterrupt:
    print('Code Stopped by Keyboard Interrupt')
    # May want to add code to stop gracefully here 
    # e.g. turn off relays or pumps

except Exception as e:
    print(f'Code stopped by unhandled exception:')
    detail = traceback.format_exception(None, e, e.__traceback__)
    reset(detail)