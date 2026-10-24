"""ESPresso Lite + Cytron UC00A flasher (only DTR is wired, so esptool cannot auto-enter the
bootloader and its RTS hard reset does nothing).

    python flash_espresso.py [COM12] [.pio/build/espresso/firmware.bin]

Hold the GPIO00 button while it waits; do NOT press RESET (that resets it mid-flash).
It pulses DTR until the ESP8266 shows 'boot mode:(1,x)' (GPIO0 low at reset), then flashes
at once over the SAME open port, so no DTR edge resets it back to normal mode."""
import re
import sys
import time

import esptool
import serial
from esptool.targets import ESP8266ROM

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM12"
BIN = sys.argv[2] if len(sys.argv) > 2 else ".pio/build/espresso/firmware.bin"
s = serial.Serial()
s.port, s.baudrate, s.timeout, s.dtr, s.rts = PORT, 74880, 0.1, False, False
s.open()
deadline, last_pulse, buf = time.time() + 150, 0.0, b""
while time.time() < deadline:
    if time.time() - last_pulse > 2.0:  # our own reset pulse every 2 s
        s.dtr = True
        time.sleep(0.05)
        s.dtr = False
        last_pulse = time.time()
    buf = (buf + s.read(256))[-400:]
    m = re.search(rb"boot mode:\((\d),\d\)", buf)
    if m:
        print("seen", m.group(0).decode(), flush=True)
        if m.group(1) == b"1":
            break
        buf = b""
else:
    sys.exit("TIMEOUT: never saw bootloader mode")

time.sleep(0.2)
s.baudrate = 115200
s.reset_input_buffer()
esp = ESP8266ROM(s, 115200)
esp.connect("no-reset")
print("CONNECTED", flush=True)
esptool.main(["--chip", "esp8266", "--after", "no-reset", "write-flash", "0x0", BIN], esp=esp)
if not s.is_open:
    s.open()
s.dtr = True  # DTR pulse = RESET: boot the new firmware (GPIO0 released by now)
time.sleep(0.1)
s.dtr = False
s.close()
print("FLASH_DONE", flush=True)
