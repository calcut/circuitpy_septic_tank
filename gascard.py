import adafruit_logging as logging
import time

class Gascard():
    def __init__(self, uart):

        # Change this to a real logger after instanciation, if logging is needed
        self.log = logging.NullLogger()

        self.uart = uart
        self.ready = False
        self.timer = time.monotonic()
        self.mode = None

        self.sample = None
        self.reference = None
        self.concentration = None
        self.temperature = None
        self.pressure = None

        self.firmware_version = None
        self.serial_number = None
        self.config_register = None
        self.frequency = None
        self.time_constant = None
        self.switches_state = None

    def restart(self):
        self.ready = False
        self.write_command('X')
        self.write_command('q')
        self.log.info('Restarting Gascard')
        while not self.ready:
            self.parse_serial()
        self.log.info('Gascard Found')
        self.read_settings()

        
    def write_command(self, string):

        # First empty the serial buffer, so we can look for acknowledgement
        self.empty_serial_buffer()

        command_bytes = bytearray(string)

        # rough code to check for acknowledgement
        response = None

        expected_responses = {
            # 'N1'   : b'N1',
            # 'X'    : b'X',
            'q'    : b' Waiting for application S-Record',
        }

        if string in expected_responses:
            expected = expected_responses[string]
        else:
            expected = command_bytes

        self.log.debug(f'writing {command_bytes}')
        self.uart.write(command_bytes + bytearray('\r'))
        line_start = None
        i=0
        while line_start != expected:
            response = self.uart.readline()
            if response:
                i+=1
                line_start = response[:len(expected)]
            
            if i >= 20:
                self.log.debug(f'Command {string} not acknowledged after {i} reads')
                return

        self.log.debug(f'Command {string} acknowledged')

    def empty_serial_buffer(self):
        nbytes = self.uart.in_waiting
        while nbytes > 0:
            self.uart.read(nbytes)
            nbytes = self.uart.in_waiting
        # Then perform a readline to make sure we are aligned with a newline
        self.uart.readline()

    def read_serial(self):

        # We only care about the latest message, so first empty the serial buffer.
        # This avoids issues where the buffer has overflowed and gives incomplete messages.
        self.empty_serial_buffer()

        # Then wait for a new message
        data = self.uart.readline()

        if data is not None:
            data_string = ''.join([chr(b) for b in data])
            if data_string.endswith('\r\n'):
                data_string = data_string[:-2]  #drop the \r\n from the string       
            self.timer = time.monotonic()
            return data_string
        else:
            time_since_data = time.monotonic() - self.timer
            if time_since_data > 5:
                self.log.warning(f'No data from gascard in {time_since_data} seconds')
                self.ready = False
            return None

    def parse_serial(self):
        data_string = self.read_serial()

        if not data_string:
            return

        if data_string[0:2] == ('N ' or 'NN'):
            self.mode='Normal'
            self.ready = True
        elif data_string[0:2] == 'N1':
            self.mode='Normal Channel'
        elif data_string[0:2] == 'X ':
            self.mode='Settings'
        else:
            self.mode = None
            if self.ready:
                self.log.warning(f'gc data NOT PARSED [{data_string}]')
            else:
                # self.log.warning(f'gc data NOT PARSED [{data_string}] writing Normal Mode')
                self.write_command('N')

        if self.mode == 'Normal':
            self.log.info('Switching to N1 Channel Mode')
            self.write_command('N1')

        if self.mode == 'Normal Channel':
            data = data_string.split(' ')
            if len(data) == 7:
                self.sample = int(data[1])
                self.reference = int(data[2])
                self.concentration = float(data[4])
                self.temperature = int(data[5])
                self.pressure = float(data[6])

        if self.mode == 'Settings':
            data = data_string.split(' ')
            if len(data) == 7:
                self.firmware_version = data[1]
                self.serial_number = data[2]
                self.config_register = data[3]
                self.frequency = data[4]
                self.time_constant = data[5]
                self.switches_state = data[6]

        self.log.debug(f'{data_string=}')
        return data_string


    def read_settings(self):
        self.write_command('X')
        while self.mode != 'Settings':
            self.parse_serial()
        self.log.debug(f'{self.firmware_version=} '
                +f'{self.serial_number=} '
                +f'{self.config_register=} '
                +f'{self.frequency=} '
                +f'{self.time_constant=} '
                +f'{self.switches_state=}')
        self.write_command('N1')