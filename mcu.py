# A helper library targeted at using Adafruit ESP32S2 Feather in a datalogger /
# iot controller.
# Essentially this just abstracts some common code to have a simpler top level.

# System and timing
import time
import rtc
from microcontroller import watchdog
from watchdog import WatchDogMode, WatchDogTimeout
import supervisor
import gc
import usb_cdc
import adafruit_logging as logging
import traceback
# from adafruit_logging import LoggingHandler

# On-board hardware
import board
import neopixel
import busio
import digitalio
import analogio

# Networking
import wifi
import ssl
import socketpool
import adafruit_minimqtt.adafruit_minimqtt as MQTT
from adafruit_io.adafruit_io import IO_MQTT
from adafruit_io.adafruit_io_errors import AdafruitIO_ThrottleError

try:
    from secrets import secrets
except ImportError:
    print("WiFi secrets are kept in secrets.py, please add them there!")
    raise

# External hardware
# import qwiic_serlcd


__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/calcut/circuitpy-heatpump"

class Mcu():
    def __init__(self, i2c_freq=50000, i2c_lookup=None, display="Sparkfun_LCD" ):

        # Initialise some key variables
        self.wifi_connected = False
        self.aio_connected = False
        self.aio_log_feed = None
        self.feeds = {} # A dict to store the values of AIO feeds
        self.aio_interval_minimum = 2 #Just an initial value, will be updated in code
        self.aio_throttled = False
        self.timer_publish = time.monotonic()
        self.timer_throttled = time.monotonic()

        # Real Time Clock in ESP32-S2 can be used to track timestamps
        self.rtc = rtc.RTC()

        # Set up logging
        # See McuLogHandler for details
        self.log = logging.getLogger('mcu')
        self.log.addHandler(McuLogHandler(self))
        self.log.level = logging.INFO

        # Use a watchdog to detect if the code has got stuck anywhere
        self.enable_watchdog()

        # Pull the I2C power pin low to enable I2C power
        self.log.info('Powering up I2C bus')
        self.i2c_power = digitalio.DigitalInOut(board.I2C_POWER_INVERTED)
        self.i2c_power_on()
        self.i2c = busio.I2C(board.SCL, board.SDA, frequency=i2c_freq)

        # Setup Neopixel, helpful to indicate status 
        self.pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, auto_write=True)
        self.pixel.RED      = 0xff0000
        self.pixel.GREEN    = 0x00ff00
        self.pixel.BLUE     = 0x0000ff
        self.pixel.MAGENTA  = 0xff00ff
        self.pixel.YELLOW   = 0xffff00
        self.pixel.CYAN     = 0x00ffff
        pixel_brightness = 0.1
        self.pixel.brightness = pixel_brightness
        self.pixel[0] = self.pixel.GREEN

        self.led = digitalio.DigitalInOut(board.LED)
        self.led.direction = digitalio.Direction.OUTPUT
        self.led.value = False

        if display == "Sparkfun_LCD":
            self.display = qwiic_serlcd.QwiicSerlcd(i2c_bus=self.i2c)
            time.sleep(0.5)  #May be needed for 20x4 display??
            self.display.setFastBacklight(255, 255, 255)
            self.display.clearScreen()
        else: 
            self.display = display

    def log_exception(self, e):
        # formats an exception to print to log as an error,
        # includues the traceback (to show code line number)
        self.log.error(traceback.format_exception(None, e, e.__traceback__))

    def enable_watchdog(self, timeout=20):
        # Setup a watchdog to reset the device if it stops responding.
        self.watchdog = watchdog
        self.watchdog.timeout=timeout #seconds
        # watchdog.mode = WatchDogMode.RESET # This does a hard reset
        self.watchdog.mode = WatchDogMode.RAISE # This prints a message then does a soft reset
        self.watchdog.feed()
        self.log.info(f'Watchdog enabled with timeout = {self.watchdog.timeout}s')

    def i2c_power_on(self):
        self.i2c_power.switch_to_output(value=False)
        time.sleep(1)


    def i2c_power_off(self):
        self.i2c_power.switch_to_output(value=True)
        time.sleep(1)

    def i2c_identify(self, i2c_lookup=None):
        while not self.i2c.try_lock():  pass

        if i2c_lookup:
            self.log.info(f'\nChecking if expected I2C devices are present:')
            
            lookup_result = i2c_lookup.copy()
            devs_present = []
            for addr in self.i2c.scan():
                devs_present.append(f'0x{addr:0{2}X}')

            for addr_hex in i2c_lookup:
                if addr_hex in devs_present:
                    lookup_result[addr_hex] = True
                    devs_present.remove(addr_hex)
                else:
                    lookup_result[addr_hex] = False
            
                self.log.info(f'{addr_hex} : {i2c_lookup[addr_hex]} = {lookup_result[addr_hex]}')
                
            if len(devs_present) > 0:
                self.log.info(f'Unknown devices found: {devs_present}')

        else:
            for device_address in self.i2c.scan():
                addr_hex = f'0x{device_address:0{2}X}'
                self.log.info(f'{addr_hex}')
            lookup_result = None

        self.i2c.unlock()
        return lookup_result

    def wifi_scan(self):
        self.log.info('\nScanning for nearby WiFi networks...')
        self.networks = []
        for network in wifi.radio.start_scanning_networks():
            self.networks.append(network)
        wifi.radio.stop_scanning_networks()
        self.networks = sorted(self.networks, key=lambda net: net.rssi, reverse=True)
        for network in self.networks:
            self.log.info(f'ssid: {network.ssid}\t rssi:{network.rssi}')


    def wifi_connect(self):
        ### WiFi ###

        # Add a secrets.py to your filesystem that has a dictionary called secrets with "ssid" and
        # "password" keys with your WiFi credentials. DO NOT share that file or commit it into Git or other
        # source control.

        i=0
        ssid = secrets["ssid"]
        password = secrets["password"]
        try:
            # Try to detect strongest wifi
            # If it is in the known networks list, use it
            self.wifi_scan()
            strongest_ssid = self.networks[0].ssid
            if strongest_ssid in secrets["networks"]:
                ssid = strongest_ssid
                password = secrets["networks"][ssid]
                self.log.info('Using strongest wifi network')
        except Exception as e:
            self.log_exception(e)

        while True:
            try:
                self.log.info(f'Wifi: {ssid}')
                wifi.radio.connect(ssid, password)
                self.log.info("Wifi Connected")
                self.pixel[0] = self.pixel.CYAN
                self.wifi_connected = True
                self.watchdog.feed()
                break
            except ConnectionError as e:
                self.log_exception(e)
                self.log.error(f"{ssid} connection failed")
                network_list = list(secrets['networks'])
                ssid = network_list[i]
                password = secrets["networks"][network_list[i]]
                time.sleep(1)
                i +=1
                if i >= len(secrets['networks']):
                    i=0

    def aio_setup(self, log_feed=None):

        self.aio_log_feed = log_feed

        # Create a socket pool
        pool = socketpool.SocketPool(wifi.radio)

        # Initialize a new MQTT Client object
        self.mqtt_client = MQTT.MQTT(
            broker="io.adafruit.com",
            username=secrets["aio_username"],
            password=secrets["aio_key"],
            socket_pool=pool,
            ssl_context=ssl.create_default_context(),
        )

        # self.mqtt_client.connect()
        # Initialize an Adafruit IO MQTT Client
        self.io = IO_MQTT(self.mqtt_client)

        # Connect the callback methods defined above to Adafruit IO
        self.io.on_connect = self.aio_connected_callback
        self.io.on_disconnect = self.aio_disconnected_callback
        self.io.on_subscribe = self.aio_subscribe_callback
        self.io.on_unsubscribe = self.aio_unsubscribe_callback
        self.io.on_message = self.aio_message_callback

        # Connect to Adafruit IO
        self.log.info("Adafruit IO...")
        try:
            self.io.connect()
        except Exception as e:
            self.log_exception(e)
            time.sleep(2)

   
    def subscribe(self, feed):
        # Subscribe to a feed from Adafruit IO
        self.io.subscribe(feed)
        # Request latest value from the feed
        self.io.get(feed)

    def unsubscribe(self, feed):
        # an unsubscribe method that mirrors the subscribe one
        self.io.unsubscribe(feed)


    def aio_connected_callback(self, client):
        # Connected function will be called when the client is connected to Adafruit IO.
        # This is a good place to subscribe to feed changes.  The client parameter
        # passed to this function is the Adafruit IO MQTT client so you can make
        # calls against it easily.
        self.log.info("Connected to AIO")
        self.aio_connected = True
        self.pixel[0] = self.pixel.MAGENTA
        self.io.subscribe_to_time("seconds")
        self.io.subscribe_to_throttling()
        self.io.subscribe_to_errors()

    def aio_subscribe_callback(self, client, userdata, topic, granted_qos):
        # This method is called when the client subscribes to a new feed.
        print("Subscribed to {0} with QOS level {1}".format(topic, granted_qos))


    def aio_unsubscribe_callback(self, client, userdata, topic, pid):
        # This method is called when the client unsubscribes from a feed.
        print("Unsubscribed from {0} with PID {1}".format(topic, pid))


    # pylint: disable=unused-argument
    def aio_disconnected_callback(self, client):
        # Disconnected function will be called when the client disconnects.
        print("Disconnected from Adafruit IO!")
        self.aio_connected = False


    def aio_message_callback(self, client, feed_id, payload):
        # Message function will be called when a subscribed feed has a new value.
        # The feed_id parameter identifies the feed, and the payload parameter has
        # the new value.
        # print("Feed {0} received new value: {1}".format(feed_id, payload))
        if feed_id == 'seconds':
            self.rtc.datetime = time.localtime(int(payload))
            # print(f'RTC syncronised')
        else:
            print(f"{feed_id} = {payload}")
            self.feeds[feed_id] = payload

    def aio_receive(self):
        if self.aio_connected:
            if self.aio_throttled:
                if (time.monotonic() - self.timer_throttled) >= 30:
                    # Reset the throttled flag if it has been over 30s
                    self.aio_throttled = False
                    self.log.warning(f'AIO throttle flag released. minimum interval currently {self.aio_interval_minimum}')
            try:
                self.io.loop(timeout=0.01) #Is this too short a timeout??
            except AdafruitIO_ThrottleError as e:
                self.log_exception(e)
                self.aio_interval_minimum += 1
                self.aio_throttled = True
                self.timer_throttled = time.monotonic()
                self.log.warning(f'AIO Throttled, increasing publish interval to {self.aio_interval_minimum}')
            except MemoryError as e:
                # self.log_exception(e)
                # https://github.com/adafruit/Adafruit_CircuitPython_MiniMQTT/issues/101
                self.log.warning("MemoryError: memory allocation failed, ignoring")
            except Exception as e:
                self.log_exception(e)
                self.log.warning(f'AIO receive error, trying longer timeout')
                self.io.loop(timeout=0.5) 

    def aio_send(self, feeds, location=None):
        if self.aio_connected:
            if not self.aio_throttled:
                if (time.monotonic() - self.timer_publish) >= self.aio_interval_minimum:
                    self.timer_publish = time.monotonic()
                    self.log.info(f"Publishing to AIO:")
                    try:
                        for feed_id in feeds.keys():
                            self.io.publish(feed_id, str(feeds[feed_id]), metadata=location)
                            self.log.info(f"{feeds[feed_id]} --> {feed_id}")
                        if location:
                            self.log.info(f"with location = {location}")

                    except Exception as e:
                        self.log_exception(e)
                        self.log.error(f"Error publishing data to AIO")

                    # Clamp the minimum interval based on number of feeds and a
                    # rate of 30 updates per minute for AIO free version.
                    min_interval = (2 * len(feeds) +1)
                    if self.aio_interval_minimum < min_interval:
                        self.aio_interval_minimum = min_interval

                else:
                    self.log.debug(f"Did not publish, aio_interval_minimum set to {self.aio_interval_minimum}s"
                                    +f" Time remaining: {int(self.aio_interval_minimum - (time.monotonic() - self.timer_publish))}s")
            else:
                self.log.warning(f'Did not publish, throttled flag = {self.aio_throttled}')

    def get_timestamp(self):
        t = self.rtc.datetime
        string = f'{t.tm_year}-{t.tm_mon:02}-{t.tm_mday:02} {t.tm_hour:02}:{t.tm_min:02}:{t.tm_sec:02}'
        return string


    def read_serial(self, send_to=None):
        # This is likely broken, it was intended to be used with asyncio
        serial = usb_cdc.console
        buffer = ''


        text = ''
        available = serial.in_waiting
        while available:
            raw = serial.read(available)
            text = raw.decode("utf-8")
            print(text, end='')
            available = serial.in_waiting

        buffer += text
        if buffer.endswith("\n"):
            input_line = buffer[:-1]
            # clear buffer
            buffer = ""
            # handle input
            if send_to:
                send_to(input_line)
            else:
                print(f'you typed: {input_line}')

class McuLogHandler(logging.LoggingHandler):

    def __init__(self, mcu_device):
        self._device = mcu_device

    def emit(self, level, msg):
        """Generate the message and write it to the AIO Feed.

        :param level: The level at which to log
        :param msg: The core message

        """

        if level == logging.INFO:
            # Don't include the "INFO" in the string, because this used a lot,
            # and is effectively the default.
            text = msg
        else:
            text = f'{logging.level_for(level)} {msg}'

        # Print to Serial
        print(text)

        # Print to AIO, only if level is WARNING or higher
        #   AND we are connected to AIO, AND a logfeed has been specified
        #   AND we are not currently throttled
        logfeed = self._device.aio_log_feed
   
        if (self._device.aio_connected 
            and logfeed
            and not self._device.aio_throttled
            and level >= logging.WARNING):

            try:
                self._device.io.publish(logfeed, text)
            except Exception as e:
                print(f'Error publishing to AIO log: {e}')

        # Print to log.txt with timestamp 
        # only works if flash is set writable at boot time
        try:
            with open('log.txt', 'a+') as f:
                ts = self._device.get_timestamp() #timestamp from the RTC
                if ts[0:4] == "2000":
                    # if the time has not been set yet, just show the seconds
                    ts = ts[-5:]
                text = f'{ts} {text}\r\n'
                f.write(text)
        except OSError as e:
            # print(f'FS not writable {self.format(level, msg)}')
            if e.args[0] == 28:  # If the file system is full...
                print(f'Filesystem full')
