# A helper library targeted at using Adafruit ESP32S2 Feather in a datalogger /
# iot controller.
# Essentially this just abstracts some common code to have a simpler top level.

# System and timing
import time
import rtc
from microcontroller import watchdog
from watchdog import WatchDogMode, WatchDogTimeout
import supervisor
import usb_cdc
import adafruit_logging as logging
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

        self.enable_watchdog()

        self.rtc = rtc.RTC()

        self.logger = logging.getLogger('mcu')
        self.logger.addHandler(CustomLogHandler(self))
        self.logger.level = logging.INFO
        self.aio_log_feed = None
        

        # Pull the I2C power pin low to enable I2C power
        print('Powering up I2C bus')
        self.i2c_power = digitalio.DigitalInOut(board.I2C_POWER_INVERTED)
        self.i2c_power_on()
        self.i2c = busio.I2C(board.SCL, board.SDA, frequency=i2c_freq)

        self.pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, auto_write=True)
        self.pixel.RED   = 0xff0000
        self.pixel.GREEN = 0x00ff00
        self.pixel.BLUE  = 0x0000ff
        pixel_color = self.pixel.GREEN
        pixel_brightness = 0.3
        self.pixel.brightness = pixel_brightness
        self.pixel[0] = pixel_color

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

        self.wifi_connected = False
        self.aio_connected = False
        self.feeds = {} # A dict to store the values of AIO feeds
        self.aio_publish_interval = 5 #Just an initial value
        self.timer_publish = time.monotonic()

    def enable_watchdog(self, timeout=20):
        # Setup a watchdog to reset the device if it stops responding.
        self.watchdog = watchdog
        self.watchdog.timeout=timeout #seconds
        # watchdog.mode = WatchDogMode.RESET # This does a hard reset
        self.watchdog.mode = WatchDogMode.RAISE # This prints a message then does a soft reset
        self.watchdog.feed()
        print(f'Watchdog enabled with timeout = {self.watchdog.timeout}s')

    def i2c_power_on(self):
        self.i2c_power.switch_to_output(value=False)
        time.sleep(1)


    def i2c_power_off(self):
        self.i2c_power.switch_to_output(value=True)
        time.sleep(1)

    def i2c_identify(self, i2c_lookup=None):
        while not self.i2c.try_lock():  pass

        if i2c_lookup:
            print(f'\nChecking if expected I2C devices are present:')
            
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
            
                print(f'{addr_hex} : {i2c_lookup[addr_hex]} = {lookup_result[addr_hex]}')
                
            if len(devs_present) > 0:
                print(f'Unknown devices found: {devs_present}')

        else:
            for device_address in self.i2c.scan():
                addr_hex = f'0x{device_address:0{2}X}'
                print(f'{addr_hex}')
            lookup_result = None

        self.i2c.unlock()
        return lookup_result

    def wifi_scan(self):
        print('\nScanning for nearby WiFi networks...')
        self.networks = []
        for network in wifi.radio.start_scanning_networks():
            self.networks.append(network)
        wifi.radio.stop_scanning_networks()
        self.networks = sorted(self.networks, key=lambda net: net.rssi, reverse=True)
        for network in self.networks:
            print("ssid:",network.ssid, "rssi:",network.rssi)


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
                print('Using strongest wifi network')

        except Exception as e:
            print(e)

        while True:
            try:
                print(f'Wifi: {ssid}')
                wifi.radio.connect(ssid, password)
                print("Wifi Connected")
                self.wifi_connected = True
                self.watchdog.feed()
                break
            except ConnectionError as e:
                print(e)
                print(f"{ssid} connection failed")
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
        print("Adafruit IO...")
        try:
            self.io.connect()
        except Exception as e:
            print(e)
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
        print("Connected to AIO")
        self.aio_connected = True
        self.io.subscribe_to_time("seconds")

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
            try:
                self.io.loop(timeout=0.01)
            except Exception as e:
                print(f'AIO receive error, using longer timeout, {str(e)}')
                self.io.loop(timeout=0.5) 

    def aio_send(self, feeds, location=None, aio_plus=False):
        if self.aio_connected:
            if (time.monotonic() - self.timer_publish) >= self.aio_publish_interval:
                self.timer_publish = time.monotonic()
                print(f"Publishing to AIO:")
                try:
                    for feed_id in feeds.keys():
                        self.io.publish(feed_id, str(feeds[feed_id]), metadata=location)
                        print(f"{feeds[feed_id]} --> {feed_id}")
                    if location:
                        print(f"with location = {location}")

                except Exception as e:
                    print(f"Error publishing data to AIO {e}")
                
                # Update the publish interval to not get throttled by AIO
                if aio_plus:
                    self.aio_publish_interval = len(feeds) +1
                else:
                    # Only allowed 30 per minute with the free version of AIO
                    self.aio_publish_interval = 2 * len(feeds) +1
                print(f"next publish in {self.aio_publish_interval}s")

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

class CustomLogHandler(logging.LoggingHandler):

    def __init__(self, mcu_device):
        self._device = mcu_device

    def emit(self, level, msg):
        """Generate the message and write it to the AIO Feed.

        :param level: The level at which to log
        :param msg: The core message

        """
        # Get a timestamp from the realtime clock
        ts = self._device.get_timestamp()
        
        # Print to Serial
        text = f'{logging.level_for(level)} {msg}'
        print(text)

        # Print to AIO
        # This will easily get throttled.... need to consider
        logfeed = self._device.aio_log_feed
   
        if self._device.aio_connected and logfeed:
            try:
                self._device.io.publish(logfeed, text)
            except Exception as e:
                print(e)

        # Print to logfile (if set writable at boot time)
        text = f'{ts} {logging.level_for(level)} {msg}'
        try:
            with open('log.txt', 'w+') as f:
                f.write(text)
            print('wrote to log.txt')
        except OSError as e:
            # print(f'FS not writable {self.format(level, msg)}')
            if e.args[0] == 28:  # If the file system is full...
                print(f'Filesystem full')
