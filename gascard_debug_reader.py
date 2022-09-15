
import board
import busio
import usb_cdc

serial_buffer = ''
uart = busio.UART(board.TX, board.RX, baudrate=57600)
serial = usb_cdc.console

def read_serial(send_to=None):
        global serial_buffer
        global uart
        serial = usb_cdc.console
        text = ''
        available = serial.in_waiting
        while available:
            raw = serial.read(available)
            text = raw.decode("utf-8")
            print(text, end='')
            available = serial.in_waiting

        # Sort out line endings
        if text.endswith("\r"):
            text = text[:-1]+"\n"
        if text.endswith("\r\n"):
            text = text[:-2]+"\n"

        serial_buffer += text
        if serial_buffer.endswith("\n"):
            input_line = serial_buffer[:-1]
            # clear buffer
            serial_buffer = ""
            # handle input

            # Call the funciton provided with input_line as argument
            command_bytes = bytearray(input_line)
            uart.write(command_bytes + bytearray('\r'))



while True:
    data = uart.readline()
    if data is not None:
        data_string = ''.join([chr(b) for b in data])
        if data_string.endswith('\r\n'):
            data_string = data_string[:-2]
        print(data_string)
    read_serial()


