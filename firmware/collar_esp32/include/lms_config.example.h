// Defaults for a freshly flashed collar. Copy to lms_config.h (gitignored) to change them,
// or skip that: everything in the first block can also be set at runtime over USB serial
// (type `help` in `pio device monitor`) and is then kept in flash across reboots.
#pragma once

// --- settable over serial: id / ssid / pass / mqtt / user / mqttpass / ppg / battery ---
#define ANIMAL_ID      "C001"
#define WIFI_SSID      ""          // empty = no Wi-Fi until set with `ssid ...` and `pass ...`
#define WIFI_PASSWORD  ""
// The laptop/Pi running Mosquitto (see infra/). Same user/password as MQTT_* in the repo .env.
#define MQTT_HOST      "10.77.218.190"
#define MQTT_PORT      1883
#define MQTT_USER      "lms"
#define MQTT_PASSWORD  "change-me"
// Pulse sensor: -1 auto-detect on I2C (MAX30102 / MAX30100 / DFRobot SEN0344),
// 1 MAX30102, 2 MAX30100, 3 DFRobot SEN0344, 4 analog pulse sensor, 0 none
#define PPG_DEFAULT    -1
// 1 only if the battery is wired to PIN_BATTERY through the divider; a floating pin reads
// random voltages and would raise false "battery low" alerts, so the default is 0 (null).
#define HAVE_BATTERY   0

// --- ESP-NOW (mode espnow) ---
// Must match ESPNOW_CHANNEL in firmware/gateway_espnow. Collars broadcast, so no MAC needed.
#define ESPNOW_CHANNEL 1

// --- timing ---
#define REPORT_SECONDS 5     // always-on: seconds between readings
#define SLEEP_SECONDS  60    // modes wifi_sleep / espnow: deep sleep between wake-ups
#define MEASURE_MS     6000  // awake time spent measuring (>= 4 s for one heart-rate window)

// --- pins. I2C is shared by the pulse sensor and the MPU6050 ---
#if CONFIG_IDF_TARGET_ESP32C3
// ESP32-C3 (SuperMini / DevKitM)
#define PIN_SDA          8
#define PIN_SCL          9
#define PIN_ONEWIRE      3    // DS18B20 data, 4.7k pull-up to 3.3V
#define PIN_BATTERY      0    // ADC1
#define PIN_PULSE_ANALOG 1    // analog pulse sensor signal (ADC1)
#else
// classic ESP32 (DevKit V1 / WROOM-32)
#define PIN_SDA          21
#define PIN_SCL          22
#define PIN_ONEWIRE      4    // DS18B20 data, 4.7k pull-up to 3.3V
#define PIN_BATTERY      35   // battery via 100k/100k divider (ADC1 only: Wi-Fi blocks ADC2)
#define PIN_PULSE_ANALOG 34   // analog pulse sensor signal (ADC1, input-only pin)
#endif
#define BATTERY_DIVIDER  2.0f
