// Copy to lms_config.h (gitignored) and fill in. One collar = one ANIMAL_ID.
#pragma once

#define ANIMAL_ID      "C001"

#define WIFI_SSID      "your-wifi"
#define WIFI_PASSWORD  "your-wifi-password"

// The laptop/Pi running Mosquitto (see infra/). Same user/password as MQTT_* in the repo .env.
#define MQTT_HOST      "10.77.218.190"
#define MQTT_PORT      1883
#define MQTT_USER      "lms"
#define MQTT_PASSWORD  "change-me"

// Seconds between readings sent to the backend.
#define REPORT_SECONDS 5

// Pins (ESP32 DevKit). I2C is shared by MAX30102 and MPU6050.
#define PIN_SDA        21
#define PIN_SCL        22
#define PIN_ONEWIRE    4    // DS18B20 data, 4.7k pull-up to 3.3V
#define PIN_BATTERY    35   // battery via 100k/100k divider (ADC1 only: Wi-Fi blocks ADC2)
#define BATTERY_DIVIDER 2.0f
