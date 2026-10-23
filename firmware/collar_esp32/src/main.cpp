// LMS cattle collar firmware.
//
// Sends one JSON reading matching common/schemas.py VitalsMsg:
//   {"animal_id":"C001","hr":68,"spo2":97,"body_temp":38.6,"activity":0.041,"steps":3,"battery":3.91,"rssi":-61}
// A sensor that is missing or has no valid reading sends null - never a made-up value.
// No timestamp: the collar has no clock, so the backend stamps the receive time.
//
// Modes (set by the PlatformIO environment, see platformio.ini):
//   LMS_MODE_WIFI        always on; MQTT to lms/collar/<id>/vitals every REPORT_SECONDS
//   LMS_MODE_WIFI_SLEEP  wake, measure MEASURE_MS, MQTT, deep sleep SLEEP_SECONDS
//   LMS_MODE_ESPNOW      wake, measure, broadcast over ESP-NOW to the gateway, deep sleep
// The radio is the big battery cost, so the sleep modes keep it off almost all the time.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <DallasTemperature.h>
#include <MPU6050.h>
#include <OneWire.h>
#include <WiFi.h>
#include <Wire.h>

#include "MAX30105.h"
#include "spo2_algorithm.h"

#if __has_include("lms_config.h")
#include "lms_config.h"
#else
#include "lms_config.example.h"
#warning "Using lms_config.example.h - copy it to lms_config.h with real Wi-Fi/MQTT settings"
#endif

#if !defined(LMS_MODE_WIFI) && !defined(LMS_MODE_WIFI_SLEEP) && !defined(LMS_MODE_ESPNOW)
#define LMS_MODE_WIFI
#endif

#if defined(LMS_MODE_ESPNOW)
#include <esp_now.h>
#include <esp_wifi.h>
#else
#include <PubSubClient.h>
WiFiClient net;
PubSubClient mqtt(net);
char topic[64];
#endif

// ---------- sensors ----------
MAX30105 pulse;
MPU6050 imu;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature thermo(&oneWire);
bool havePulse = false, haveImu = false, haveThermo = false;

// MAX30102 samples for the Maxim SpO2/HR algorithm (25 samples/s, 4 s window)
const int32_t PULSE_BUF = 100;
uint32_t irBuf[PULSE_BUF], redBuf[PULSE_BUF];
int32_t pulseIdx = 0;
bool pulseFull = false;

// activity: mean |acceleration| - 1 g over the window, and a simple step counter
const float ACC_LSB_PER_G = 16384.0f;  // +-2 g range
double actSum = 0;
uint32_t actN = 0, steps = 0, lastStepMs = 0, lastImu = 0, lastReport = 0;
bool stepHigh = false;
const float STEP_HIGH_G = 1.25f, STEP_LOW_G = 1.05f;
const uint32_t STEP_MIN_MS = 350;

RTC_DATA_ATTR uint32_t wakeCount = 0;  // survives deep sleep

void setupSensors() {
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  havePulse = pulse.begin(Wire, I2C_SPEED_FAST);
  // LED 0x1F, average 4, red+IR, 100 sps / 4 = 25 effective sps, pulse width 411, ADC range 4096
  if (havePulse) pulse.setup(0x1F, 4, 2, 100, 411, 4096);
  imu.initialize();
  haveImu = imu.testConnection();
  if (haveImu) imu.setFullScaleAccelRange(MPU6050_ACCEL_FS_2);
  thermo.begin();
  haveThermo = thermo.getDeviceCount() > 0;
  analogSetPinAttenuation(PIN_BATTERY, ADC_11db);
  Serial.printf("collar %s  max30102:%d mpu6050:%d ds18b20:%d  wake #%lu\n", ANIMAL_ID, havePulse, haveImu,
                haveThermo, (unsigned long)wakeCount);
}

void samplePulse() {
  if (!havePulse) return;
  pulse.check();
  while (pulse.available()) {
    redBuf[pulseIdx] = pulse.getFIFORed();
    irBuf[pulseIdx] = pulse.getFIFOIR();
    pulse.nextSample();
    if (++pulseIdx >= PULSE_BUF) {
      pulseIdx = 0;
      pulseFull = true;
    }
  }
}

void sampleImu() {
  if (!haveImu || millis() - lastImu < 20) return;  // 50 Hz
  lastImu = millis();
  int16_t ax, ay, az;
  imu.getAcceleration(&ax, &ay, &az);
  float g = sqrtf((float)ax * ax + (float)ay * ay + (float)az * az) / ACC_LSB_PER_G;
  actSum += fabsf(g - 1.0f);
  actN++;
  // step = a peak above STEP_HIGH_G after dropping below STEP_LOW_G, at most one per STEP_MIN_MS
  if (!stepHigh && g > STEP_HIGH_G && millis() - lastStepMs > STEP_MIN_MS) {
    stepHigh = true;
    steps++;
    lastStepMs = millis();
  } else if (stepHigh && g < STEP_LOW_G) {
    stepHigh = false;
  }
}

float batteryVolts() { return analogReadMilliVolts(PIN_BATTERY) * BATTERY_DIVIDER / 1000.0f; }

// Build one reading and reset the window counters. Returns the JSON length.
size_t buildReading(char* out, size_t cap, int rssi) {
  JsonDocument doc;
  doc["animal_id"] = ANIMAL_ID;
  doc["hr"] = nullptr;
  doc["spo2"] = nullptr;
  if (havePulse && pulseFull) {
    // the algorithm wants the buffer in time order starting at the oldest sample
    static uint32_t ir[PULSE_BUF], red[PULSE_BUF];
    for (int32_t i = 0; i < PULSE_BUF; i++) {
      ir[i] = irBuf[(pulseIdx + i) % PULSE_BUF];
      red[i] = redBuf[(pulseIdx + i) % PULSE_BUF];
    }
    int32_t spo2, hr;
    int8_t spo2Valid, hrValid;
    maxim_heart_rate_and_oxygen_saturation(ir, PULSE_BUF, red, &spo2, &spo2Valid, &hr, &hrValid);
    bool contact = ir[PULSE_BUF - 1] > 50000;  // no skin contact -> weak IR
    if (contact && hrValid && hr > 20 && hr < 250) doc["hr"] = hr;
    if (contact && spo2Valid && spo2 > 50 && spo2 <= 100) doc["spo2"] = spo2;
  }
  doc["body_temp"] = nullptr;
  if (haveThermo) {
    thermo.requestTemperatures();
    float t = thermo.getTempCByIndex(0);
    if (t != DEVICE_DISCONNECTED_C && t > 25 && t < 45) doc["body_temp"] = roundf(t * 100) / 100;
  }
  if (actN) doc["activity"] = roundf(actSum / actN * 10000) / 10000;
  else doc["activity"] = nullptr;
  if (haveImu) doc["steps"] = steps;
  else doc["steps"] = nullptr;
  doc["battery"] = roundf(batteryVolts() * 1000) / 1000;
  if (rssi) doc["rssi"] = rssi;
  actSum = 0;
  actN = 0;
  steps = 0;
  return serializeJson(doc, out, cap);
}

// ---------------------------------------------------------------- Wi-Fi + MQTT
#if !defined(LMS_MODE_ESPNOW)
bool connectWifi(uint32_t timeoutMs) {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) delay(100);
  Serial.printf("wifi %s\n", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "FAILED");
  return WiFi.status() == WL_CONNECTED;
}

bool connectMqtt() {
  if (mqtt.connected()) return true;
  if (WiFi.status() != WL_CONNECTED) return false;
  String id = String("lms-collar-") + ANIMAL_ID;
  bool ok = mqtt.connect(id.c_str(), MQTT_USER, MQTT_PASSWORD);
  if (!ok) Serial.printf("mqtt failed rc=%d\n", mqtt.state());
  return ok;
}

bool publishReading() {
  char payload[256];
  size_t n = buildReading(payload, sizeof(payload), WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0);
  Serial.println(payload);
  return mqtt.connected() && mqtt.publish(topic, (const uint8_t*)payload, n, false);
}
#endif

// ---------------------------------------------------------------- ESP-NOW
#if defined(LMS_MODE_ESPNOW)
volatile bool sendDone = false;

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onSent(const wifi_tx_info_t*, esp_now_send_status_t status) {
#else
void onSent(const uint8_t*, esp_now_send_status_t status) {
#endif
  Serial.printf("esp-now send %s\n", status == ESP_NOW_SEND_SUCCESS ? "ok" : "failed");
  sendDone = true;
}

void sendEspNow() {
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("esp-now init failed");
    return;
  }
  esp_now_register_send_cb(onSent);
  esp_now_peer_info_t peer = {};
  memset(peer.peer_addr, 0xFF, 6);  // broadcast: the gateway listens to everyone on the channel
  peer.channel = ESPNOW_CHANNEL;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  char payload[250];  // ESP-NOW frames carry at most 250 bytes
  size_t n = buildReading(payload, sizeof(payload), 0);
  Serial.println(payload);
  esp_now_send(peer.peer_addr, (const uint8_t*)payload, n);
  uint32_t t0 = millis();
  while (!sendDone && millis() - t0 < 200) delay(5);
}
#endif

// ---------------------------------------------------------------- sleep modes
#if defined(LMS_MODE_WIFI_SLEEP) || defined(LMS_MODE_ESPNOW)
void measureWindow() {
  uint32_t t0 = millis();
  while (millis() - t0 < MEASURE_MS) {
    samplePulse();
    sampleImu();
    delay(2);
  }
}

void goToSleep() {
  if (havePulse) pulse.shutDown();
  if (haveImu) imu.setSleepEnabled(true);
  WiFi.mode(WIFI_OFF);
  Serial.printf("sleeping %d s\n", SLEEP_SECONDS);
  Serial.flush();
  esp_deep_sleep((uint64_t)SLEEP_SECONDS * 1000000ULL);
}
#endif

void setup() {
  Serial.begin(115200);
  delay(100);
  wakeCount++;
  setupSensors();
#if defined(LMS_MODE_WIFI) || defined(LMS_MODE_WIFI_SLEEP)
  snprintf(topic, sizeof(topic), "lms/collar/%s/vitals", ANIMAL_ID);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
#endif

#if defined(LMS_MODE_WIFI_SLEEP)
  measureWindow();  // radio off while measuring
  if (connectWifi(8000) && connectMqtt()) {
    publishReading();
    mqtt.loop();
    delay(50);  // let the TCP send finish before cutting power
    mqtt.disconnect();
  }
  goToSleep();
#elif defined(LMS_MODE_ESPNOW)
  measureWindow();
  sendEspNow();
  goToSleep();
#else
  connectWifi(15000);
  connectMqtt();
#endif
}

void loop() {
#if defined(LMS_MODE_WIFI)
  samplePulse();
  sampleImu();
  if (millis() - lastReport >= REPORT_SECONDS * 1000UL) {
    lastReport = millis();
    connectWifi(15000);
    connectMqtt();
    publishReading();
  }
  mqtt.loop();
#endif
}
