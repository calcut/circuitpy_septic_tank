import adafruit_logging as logging
import time

class Gascard():
    def __init__(self, uart):

        # No handler is provided here, add one after instanciation, if logging is needed
        self.log = logging.getLogger('Gascard')

        self.uart = uart
        self.ready = False
        self.timer = time.monotonic()
        self.mode = None

        self.concentration = None
        self.temperature = None
        self.pressure = None

    def empty_serial_buffer(self):
        nbytes = self.uart.in_waiting
        while nbytes > 0:
            scrap1 = self.uart.read(nbytes)
            # print(f'{scrap1=}')
            nbytes = self.uart.in_waiting
        # Then perform a readline to make sure we are aligned with a newline
        scrap = self.uart.readline()
        # self.log.debug(f'{scrap=}')

    def read_serial(self):

        # We only care about the latest message, so first empty the serial buffer.
        # This avoids issues where the buffer has overflowed and gives incomplete messages.
        self.empty_serial_buffer()

        # Then wait for a new message
        data = self.uart.readline()
        # self.log.debug(f'{data=}')

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
        try:
            self.log.debug(f'{data_string=}')

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
                    self.log.warning('possible startup issue detected')
                    self.log.warning(f'{data_string=}')

            if self.mode == 'Normal':
                data = data_string.split(' ')
                try:
                    self.concentration = float(data[1])
                except ValueError:
                    self.log.debug(f'Gascard error {data_string=}')
                    self.concentration = -100.0
                self.temperature = int(data[6])
                self.pressure = float(data[7])

           
        except Exception as e:
            self.log.warning(str(e))
            self.log.warning(f'{data_string=}')
            raise

        return data_string