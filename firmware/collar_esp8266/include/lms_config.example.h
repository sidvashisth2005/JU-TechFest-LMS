// Defaults for a freshly flashed ESP8266 collar. Copy to lms_config.h (gitignored) to change
// them, or set id / ssid / pass / mqtt / user / mqttpass over USB serial (type `help`); those
// are saved in flash (LittleFS) and survive reboots and re-flashing of the same layout.
#pragma once

#define ANIMAL_ID      "C001"
#define WIFI_SSID      ""          // empty = no Wi-Fi until set with `ssid ...` and `pass ...`
#define WIFI_PASSWORD  ""
// The laptop/Pi running Mosquitto (see infra/). Same user/password as MQTT_* in the repo .env.
#define MQTT_HOST      "10.207.184.190"
#define MQTT_PORT      1883
#define MQTT_USER      "lms"
#define MQTT_PASSWORD  "change-me"

// --- timing ---
#define REPORT_SECONDS 5    // vitals (activity/steps) to lms/collar/<id>/vitals
#define ENV_SECONDS    30   // DHT22 air reading to lms/barn/<id>-collar/env

// --- pins (ESPresso Lite V2 labels) ---
#define PIN_SDA     4    // top header "SDA": GY-521 + OLED share I2C
#define PIN_SCL     5    // top header "SCL"
#define PIN_DHT     12   // header "3V3 12 14 GND": DHT22 data on 12 (10k pull-up to 3V3)
#define PIN_BUTTON  13   // on-board GPIO13 button: next OLED page
#define PIN_LED     2    // on-board GPIO2 LED (active low): blinks on each send
