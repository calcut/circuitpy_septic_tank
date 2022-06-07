import supervisor
supervisor.disable_autoreload()

# If CIRCUITPY drive is writable (configured in boot.py) this will update code files over-the-air
from circuitpy_mcu.ota_bootloader import Bootloader
url = 'https://raw.githubusercontent.com/calcut/circuitpy_septic_tank/main/ota_list.py'
bl = Bootloader(url)

code = '/circuitpy_septic_tank/septic_tank.py'
supervisor.set_next_code_file(code, reload_on_success=False)
supervisor.reload()