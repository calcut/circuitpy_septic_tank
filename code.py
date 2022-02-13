# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT
import supervisor
import time

code = 'heating_relay.py'
# print('booted')



supervisor.disable_autoreload()
supervisor.set_next_code_file(code, reload_on_success=False)
# time.sleep(0.1)
supervisor.reload()