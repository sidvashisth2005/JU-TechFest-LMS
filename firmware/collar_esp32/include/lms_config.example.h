// Copy to lms_config.h (gitignored) and fill in. One collar = one ANIMAL_ID.
#pragma once

#define ANIMAL_ID      "C001"

// --- Wi-Fi + MQTT (modes wifi and wifi_sleep) ---
#define WIFI_SSID      "your-wifi"
#define WIFI_PASSWORD  "your-wifi-password"
// The laptop/Pi running Mosquitto (see infra/). Same user/password as MQTT_* in the repo .env.
#define MQTT_HOST      "10.77.218.190"
#define MQTT_PORT      1883
#define MQTT_USER      "lms"
#define MQTT_PASSWORD  "change-me"

// --- ESP-NOW (mode espnow) ---
// Must match ESPNOW_CHANNEL in firmware/gateway_espnow. Collars broadcast, so no MAC needed.
#define ESPNOW_CHANNEL 1

// --- timing ---
#define REPORT_SECONDS 5     // mode wifi: seconds between readings
#define SLEEP_SECONDS  60    // modes wifi_sleep / espnow: deep sleep between wake-ups
#define MEASURE_MS     6000  // awake time spent measuring (>= 4 s for one heart-rate window)

// --- pins (ESP32 DevKit). I2C is shared by MAX30102 and MPU6050 ---
#define PIN_SDA        21
#define PIN_SCL        22
#define PIN_ONEWIRE    4    // DS18B20 data, 4.7k pull-up to 3.3V
#define PIN_BATTERY    35   // battery via 100k/100k divider (ADC1 only: Wi-Fi blocks ADC2)
#define BATTERY_DIVIDER 2.0f
