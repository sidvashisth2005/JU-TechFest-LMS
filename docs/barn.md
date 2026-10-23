# Barn station (Sense HAT Pi)

Barn Pi `rpi-1` + Sense HAT v1. Code: `barn/sensehat_pub.py` (hardware) + `barn/station.py` (logic, tested on the laptop).
Service: `bash ~/lms/infra/pi/lms-barn.sh on|off|toggle|start|stop|restart|status|logs`.

## Kya-kya naapta hai

| Har 30 s (`lms/barn/barn1/env`) | Sensor |
|---|---|
| Temperature (CPU heat correction ke saath), humidity, pressure | HTS221, LPS25H |
| THI, dew point (dashboard pe calculate) | temp + humidity |
| Tilt: station apni lagi hui position se kitne degree jhuka | accelerometer |
| Vibration: RMS g, pichli reading se | accelerometer |
| Heading (compass, uncalibrated), magnetic field µT | magnetometer + gyro |

| Turant (`lms/barn/barn1/event`) | Kab |
|---|---|
| `knock` | jhatka ≥ 0.5 g (koi janwar takraya). 5 s me ek baar |
| `tilted` / `level` | 30° se zyada jhuka, 3 s tak / wapas 12° ke andar |
| `gate_open` / `gate_closed` | `BARN_GATE=1` + gate pe magnet: field 25 µT se zyada badla, 30 s tak |
| `ack` | joystick beech se 2 s dabaya |
| `hello` | service start hui (detail me Pi ka IP) |

## Alerts (backend)

| Alert | Severity | Kab | Khud band |
|---|---|---|---|
| `heat_stress` | info/warning/critical | THI 72 / 79 / 89 | THI < 70 |
| `storm_risk` | warning | pressure 3 h me ≥ 3 hPa gira | gir < 1.5 hPa |
| `station_tilted` | warning | `tilted` event | `level` event |
| `gate_open` | warning | `gate_open` event | `gate_closed` event |
| `station_bumped` | info | `knock` event | 30 min tak koi knock nahi |
| `sensor_offline` | info | station 15 min se chup | agli reading pe |

Warning/critical alerts Telegram pe bhi jaate hain. Backend har station ko uske open alerts ki ginti
retained MQTT pe bhejta hai (`lms/barn/barn1/state`), LED usi se "!" dikhata hai.

## LED + joystick

| Joystick | Kaam |
|---|---|
| ⬅️ ➡️ | screen badlo (neeche order). Har value se pehle uska naam scroll hota hai, jaise `TEMP 27.2C` |
| click (beech se) | abhi reading bhejo (blue flash) |
| beech se 2 s dabaye rakho | is station ke saare open alerts acknowledge (green flash) |
| ⬆️ ⬇️ | bright / dim |
| 30 s kuch nahi | wapas home |

Screens ka order (➡️ se aage, ⬅️ se peeche, aakhri ke baad wapas home):

| # | Screen | LED pe | Scroll ke beech |
|---|---|---|---|
| 0 | Home | S (ya "!" jab alert open ho) | – |
| 1 | Temperature | `TEMP 27.2C` | T |
| 2 | Humidity | `HUMIDITY 34.5%` | H |
| 3 | THI | `THI 71.6` | I |
| 4 | Dew point | `DEW POINT 10.0C` | D |
| 5 | Pressure | `PRESSURE 975.9hPa` (+3 h trend, 1 h baad) | P |
| 6 | Alerts | `ALERTS 1` | A |
| 7 | Spirit level | `LEVEL`, phir live bubble | – |
| 8 | Compass | `COMPASS`, phir live arrow | – |
| 9 | IP | `IP 10.143.195.209` | @ |

Home screen: koi alert open nahi → `BARN_LETTER` (S) THI ke rang pe (hara/peela/orange/laal).
Alert open → "!" alert ke rang pe (neela info, orange warning, laal critical).
Spirit level: bubble beech me + hara = seedha. Compass: laal nok = magnetic north (motors/loha paas ho to galat).
IP screen: hotspot badalne pe Pi ka naya IP yahin se padh lo.

## Settings (`~/lms/.env` on the Pi)

`MQTT_HOST` (laptop IP), `BARN_STATION`, `BARN_INTERVAL`, `BARN_LETTER=S`, `BARN_BRIGHT=1`,
`BARN_SCROLL=0.15` (scroll speed, zyada = dheere),
`BARN_KNOCK_G=0.5`, `BARN_TILT_DEG=30`, `BARN_GATE=1`, `BARN_GATE_UT=25`, `BARN_GATE_OPEN_S=30`.
Badalne ke baad `lms-barn.sh restart`.

Tilt aur gate ka "normal" start-up pe seekha jaata hai: service tab start karo jab station apni jagah
lagi ho aur gate band ho.

## Limits

- Temperature 1–3 °C zyada aa sakta hai (HAT CPU ke upar). Asli thermometer se `--factor` calibrate karo, ya ribbon cable.
- Compass calibrate nahi hai (RTIMULib calibration nahi kiya), heading sirf andaza hai.
- v1 board: colour/light sensor nahi hai.
- Rover ki location sirf accelerometer se nahi nikal sakti (drift); encoders + gyro heading chahiye. Rover pe kaunsa IMU lagega (MPU6050 / Sense HAT / BNO055) abhi decide hona baaki hai.
