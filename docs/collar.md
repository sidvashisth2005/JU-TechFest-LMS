# Collar: hackathon day guide (ESP32 main, UNO backup)

**Plan:** ESP32 collar Wi-Fi se data bhejega (main). Kuch fail ho to ESP32 ya UNO ko USB cable se laptop pe lagao, aur wahi data cable se aayega (backup). Dashboard ko fark nahi padta ki data kaunse raaste se aaya.

```
MAIN     ESP32 ──Wi-Fi──► laptop Mosquitto :1883 ──► dashboard
BACKUP 1 ESP32 ──USB───► laptop serial_bridge ──► Mosquitto ──► dashboard   (Wi-Fi nahi chala)
BACKUP 2 UNO   ──USB───► laptop serial_bridge ──► Mosquitto ──► dashboard   (ESP32 hi nahi chala)
BACKUP 3 sirf simulator (50 virtual cows) + video
```

PPG (pulse sensor) ka board abhi pata nahi hai, isliye code 4 tarah ke board chala leta hai:

| PPG board | Pehchaan | ESP32 | UNO env |
|---|---|---|---|
| **MAX30102** (purple/black chhota board, "MAX30102" likha) | I2C 0x57, part id 0x15 | auto-detect ✅ | `uno` |
| **MAX30100** (purana, aksar laal board) | I2C 0x57, part id 0x11 | auto-detect ✅ | `uno_max30100` |
| **DFRobot Gravity SEN0344** (DFRobot logo, Gravity connector) | I2C 0x57, koi aur id | auto-detect ✅ | `uno_dfrobot` |
| **Analog Pulse Sensor** (gol hara board, dil ka logo, 3 taar) | analog pin, I2C nahi | `ppg analog` command | `uno_analog` |

Kharidne ka mauka ho to **MAX30102** lo: heart rate + SpO₂ dono deta hai, aur sabse zyada test hua library isi ki hai. Analog sensor sirf heart rate deta hai.

Accelerometer: koi bhi **MPU6050 / GY-521** (MPU6500/MPU9250 clones bhi chalenge). Body temperature: **DS18B20** waterproof probe + 4.7 kΩ resistor (optional; na ho to `body_temp` null jaayega).

---

## 1. Wiring

### ESP32 DevKit V1 / WROOM-32 (classic, 30/38 pin)
| Sensor pin | ESP32 pin |
|---|---|
| PPG VIN/VCC + MPU6050 VCC | **3V3** |
| PPG GND + MPU6050 GND | **GND** |
| PPG SDA + MPU6050 SDA | **GPIO 21** |
| PPG SCL + MPU6050 SCL | **GPIO 22** |
| Analog pulse sensor signal (S) | **GPIO 34** (VCC 3V3, GND) |
| DS18B20 data (peela) | **GPIO 4**, aur 4.7 kΩ resistor DATA se 3V3 tak |
| Battery (optional) | 100k/100k divider ka beech wala point → **GPIO 35**, phir `battery on` |

### ESP32-C3 (SuperMini / DevKitM)
SDA **GPIO 8**, SCL **GPIO 9**, analog pulse **GPIO 1**, DS18B20 **GPIO 3**, battery **GPIO 0**. Flash ke liye env `wifi_c3`.

### Arduino UNO (backup)
SDA **A4**, SCL **A5**, analog pulse **A0**, DS18B20 **D2** (4.7 kΩ D2 se 5V tak). MAX30102/MAX30100 board pe regulator ho to 5V, warna 3.3V.

Dhyan do: I2C pe dono sensor **same 2 taar** share karte hain (SDA sab SDA pe, SCL sab SCL pe). Sab ka GND common hona chahiye.

---

## 2. ESP32 flash karna (laptop, PowerShell)

```powershell
cd D:\Project\LMS\firmware\collar_esp32
..\..\.venv\Scripts\pio run -e wifi -t upload        # ESP32-C3 ho to: -e wifi_c3
..\..\.venv\Scripts\pio device monitor               # serial monitor (Ctrl+C se bahar)
```
- Upload "Failed to connect" bole: board ka **BOOT** button dabaye rakho jab tak "Connecting..." chale.
- COM port hi na dikhe: USB cable sirf charging wali hai (data wali lo), ya CH340/CP210x driver install karo.
- Pehli baar libraries download hongi (internet chahiye, 1–2 min).

Monitor mein aisa dikhna chahiye:
```
collar C001  mode:wifi  ppg:max30102 (wanted auto)  imu:yes (0x68 id 0x68)  ds18b20:no  wake #1
no Wi-Fi set: readings go to USB serial only (type help)
ready (type help for commands)
{"animal_id":"C001","hr":null,"spo2":null,"body_temp":null,"activity":0.0021,"steps":0,"battery":null}
```

## 3. Sensors check (monitor mein type karo)

```
scan        → I2C par kya mila: 0x57 MAX30102..., 0x68 MPU6050...
raw         → live raw values (ungli rakho to pulse ka number badlega); dobara raw = band
show        → settings + kya chal raha hai
```
`hr` ka number aane ke liye ungli halke se, bina hilaye, ~5–10 second sensor pe rakho. Tez roshni mein haath se dhak do. Analog sensor ho to: `ppg analog`, phir `reboot`.

## 4. Wi-Fi + laptop se jodna (reflash ki zaroorat nahi)

1. Laptop aur ESP32 **ek hi Wi-Fi** pe hone chahiye. ESP32 **sirf 2.4 GHz** Wi-Fi pakadta hai: phone hotspot mein "2.4 GHz" / "Extend compatibility" on karo.
2. Laptop ka IP: PowerShell mein `ipconfig` → Wi-Fi adapter → IPv4 Address (jaise `192.168.43.120`).
3. Monitor mein:
   ```
   ssid Galaxy A16 5G 9365
   pass <hotspot password>
   mqtt 192.168.43.120
   user lms
   mqttpass <MQTT_PASSWORD wali value, laptop .env se khud dekh ke>
   id C001
   reboot
   ```
4. Ab dikhega `wifi: connected, ip ...` aur `mqtt 192.168.43.120:1883 connected`. Dashboard pe Herd page par C001 ka data aane lagega.
5. Laptop pe pehle se chalna chahiye: `.\infra\run_all.ps1 -Simulator` aur firewall rule for port 1883 (`docs/setup.md` section 5, admin PowerShell, ek baar).

Settings ESP32 ki flash mein save rehti hain. Agli baar power on karte hi khud jud jaayega.

| Monitor mein error | Matlab | Ilaaj |
|---|---|---|
| `wifi: connecting...` baar baar | Wi-Fi nahi mila | SSID/password check karo, hotspot 2.4 GHz pe ho |
| `mqtt ... failed rc=-2` | Laptop tak nahi pahunch raha | IP sahi hai? Firewall rule laga? Laptop same Wi-Fi pe? `run_all` chal raha hai? |
| `rc=4` ya `rc=5` | MQTT user/password galat | `user` / `mqttpass` dobara set karo |
| `no pulse sensor found` | I2C pe PPG nahi | `scan`, taar check karo; analog sensor hai to `ppg analog` |

## 5. Backup 1: ESP32 USB cable se (Wi-Fi fail)

ESP32 har reading USB pe bhi print karta hai. Monitor band karo (port free hona chahiye), phir laptop pe:
```powershell
.\infra\run_all.ps1 -Simulator -Collar auto       # ya -Collar COM7 agar auto na mile
Get-Content logs\collar.log -Tail 5                # "C001 hr=.. spo2=.." dikhna chahiye
```
`auto` Bluetooth wale COM ports ko chhod deta hai aur Arduino/ESP32 board dhoondhta hai.

## 6. Backup 2: Arduino UNO

PPG board ke hisaab se env chuno (upar wali table):
```powershell
cd D:\Project\LMS\firmware\uno_bridge
..\..\.venv\Scripts\pio run -e uno -t upload          # ya uno_max30100 / uno_dfrobot / uno_analog
..\..\.venv\Scripts\pio device monitor
```
Pehli line: `{"status":"ready","ppg":"max30102","ppg_ok":true,"imu":true,...}`. Agar `ppg_ok:false` aaye to galat env hai (ya wiring galat). Doosra env try karo. Monitor band karke `.\infra\run_all.ps1 -Collar auto`.

Pi pe lagana ho (laptop ki jagah): Pi ki `~/lms-rover/.env` mein `UNO_PORT=auto`, phir `~/lms-rover/infra/pi/lms-pi.sh start uno`.

## 7. Demo se pehle checklist
- [ ] `scan` mein PPG + MPU6050 dono dikh rahe hain
- [ ] Ungli rakhne pe 10 s mein `hr` number aata hai
- [ ] Collar hilane pe `activity` badhta hai, aur chalne/jhatkon pe `steps` badhte hain
- [ ] Dashboard Herd page pe C001 live update ho raha hai
- [ ] USB cable + `-Collar auto` backup ek baar try kar liya
- [ ] UNO + sahi env pehle se flash karke bag mein

## Modes (baad ke liye)
| Env | Kya karta hai | Kab |
|---|---|---|
| `wifi` / `wifi_c3` | Hamesha on, har 5 s reading | **Demo** |
| `wifi_sleep` | 60 s so jaata hai, 6 s naapta hai, bhejta hai | Lambi battery |
| `espnow` / `espnow_c3` | Router ke bina, gateway ESP32 ko radio se | Khet / bina Wi-Fi |

Sleep modes mein setting badalni ho to: reset dabao aur 6 s ke andar koi bhi command type karo (jaise `show`). Collar jaagta rahega jab tak `reboot` na karo.
