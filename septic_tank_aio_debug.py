import time
import supervisor
import wifi, ssl, socketpool
import adafruit_minimqtt.adafruit_minimqtt as MQTT
from adafruit_io.adafruit_io import IO_MQTT
import adafruit_requests

from secrets import secrets

AIO_GROUP = 'septic-dev'

def aio_subscribe_callback(client, userdata, topic, granted_qos):
    print(f"Subscribed to {topic} with QOS level {granted_qos}")


ssid = secrets["ssid"]
password = secrets["password"]
wifi.radio.connect(ssid, password)

pool = socketpool.SocketPool(wifi.radio)
requests = adafruit_requests.Session(pool, ssl.create_default_context())

mqtt_client = MQTT.MQTT(
    broker="io.adafruit.com",
    username=secrets["aio_username"],
    password=secrets["aio_key"],
    socket_pool=pool,
    ssl_context=ssl.create_default_context(),
)

io = IO_MQTT(mqtt_client)
io.on_subscribe = aio_subscribe_callback
io.connect()

# io.subscribe('TC1')
# io.subscribe('TC2')
# io.subscribe('TC3')
# io.subscribe('TC4')
# io.subscribe('TC5')
# io.subscribe('TC6')
# io.subscribe('TC7')
# io.subscribe('TC8')


io.subscribe(f'{AIO_GROUP}.pump1-speed')
io.subscribe(f'{AIO_GROUP}.pump2-speed')
io.subscribe(f'{AIO_GROUP}.pump3-speed')
io.subscribe(f'{AIO_GROUP}.gc1')
io.subscribe(f'{AIO_GROUP}.gc2')
io.subscribe(f'{AIO_GROUP}.gc3')
io.subscribe(f'{AIO_GROUP}.tc1')
io.subscribe(f'{AIO_GROUP}.tc2')
io.subscribe(f'{AIO_GROUP}.tc3')
io.subscribe(f'{AIO_GROUP}.tc4')
io.subscribe(f'{AIO_GROUP}.ph1')
io.subscribe(f'{AIO_GROUP}.ph2')
io.subscribe(f'{AIO_GROUP}.ph3')


print(f'BOOT complete')
time.sleep(2)
supervisor.reload()