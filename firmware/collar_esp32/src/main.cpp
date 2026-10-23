// LMS cattle collar firmware (ESP32 / ESP32-C3).
//
// Sends one JSON reading matching common/schemas.py VitalsMsg:
//   {"animal_id":"C001","hr":68,"spo2":97,"body_temp":38.6,"activity":0.041,"steps":3,"battery":3.91,"rssi":-61}
// A sensor that is missing or has no valid reading sends null - never a made-up value.
// No timestamp: the collar has no clock, so the backend stamps the receive time.
//
// Every reading is also printed as a JSON line on USB serial, so a collar on a USB cable
// works even without Wi-Fi: `python -m barn.serial_bridge --port auto` on the laptop or Pi
// forwards the lines to MQTT (the same path the UNO backup uses).
//
// Pulse sensor: MAX30102, MAX30100, DFRobot SEN0344 (auto-detected on I2C) or an analog
// pulse sensor (set with `ppg analog`). See src/ppg.cpp. Accelerometer: any MPU6050-family
// chip. Body temperature: DS18B20 (optional).
//
// Modes (set by the PlatformIO environment, see platformio.ini):
//   LMS_MODE_WIFI        always on; MQTT to lms/collar/<id>/vitals every REPORT_SECONDS
//   LMS_MODE_WIFI_SLEEP  wake, measure MEASURE_MS, MQTT, deep sleep SLEEP_SECONDS
//   LMS_MODE_ESPNOW      wake, measure, broadcast over ESP-NOW to the gateway, deep sleep
// In the sleep modes, typing any serial command during the awake window keeps the collar
// awake (always-on behaviour) until `reboot`, so it can be configured and checked.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <DallasTemperature.h>
#include <LmsImu.h>
#include <OneWire.h>
#include <WiFi.h>
#include <Wire.h>

#include "config.h"
#include "ppg.h"
#include "settings.h"

#ifdef LMS_USING_EXAMPLE_CONFIG
#warning "Using lms_config.example.h defaults - set Wi-Fi/MQTT over serial (type help) or create lms_config.h"
#endif

#if !defined(LMS_MODE_WIFI) && !defined(LMS_MODE_WIFI_SLEEP) && !defined(LMS_MODE_ESPNOW)
#define LMS_MODE_WIFI
#endif

#if defined(LMS_MODE_ESPNOW)
#include <esp_now.h>
#include <esp_wifi.h>
static const char* MODE_NAME = "espnow";
#else
#include <PubSubClient.h>
WiFiClient net;
PubSubClient mqtt(net);
String topic;
#if defined(LMS_MODE_WIFI_SLEEP)
static const char* MODE_NAME = "wifi_sleep";
#else
static const char* MODE_NAME = "wifi";
#endif
#endif

// ---------- sensors ----------
LmsImu imu;
LmsActivity act;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature thermo(&oneWire);
PpgKind ppg = PPG_NONE;
bool haveImu = false, haveThermo = false;
uint32_t lastImu = 0, lastReport = 0, lastRaw = 0;
float lastG = 0;

RTC_DATA_ATTR uint32_t wakeCount = 0;  // survives deep sleep

void setupSensors() {
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  ppg = ppgBegin(cfg.ppg);
  haveImu = imu.begin(Wire);
  thermo.begin();
  haveThermo = thermo.getDeviceCount() > 0;
  if (haveThermo) {
    thermo.setWaitForConversion(false);  // a blocking read takes 750 ms and starves the pulse sensor
    thermo.requestTemperatures();
  }
  if (cfg.battery) analogSetPinAttenuation(PIN_BATTERY, ADC_11db);
  Serial.printf("collar %s  mode:%s  ppg:%s (wanted %s)  imu:%s", cfg.id.c_str(), MODE_NAME, ppgName(ppg),
                ppgName(cfg.ppg), haveImu ? "yes" : "no");
  if (haveImu) Serial.printf(" (0x%02X id 0x%02X)", imu.addr, imu.whoami);
  Serial.printf("  ds18b20:%s  wake #%lu\n", haveThermo ? "yes" : "no", (unsigned long)wakeCount);
  if (ppg == PPG_NONE) Serial.println("no pulse sensor found - type scan to check wiring, help for commands");
}

void sampleImu() {
  if (!haveImu || millis() - lastImu < 20) return;  // 50 Hz
  lastImu = millis();
  if (imu.readG(lastG)) act.add(lastG, lastImu);
}

void sampleAll() {
  settingsPoll();
  ppgSample();
  sampleImu();
  if (rawMode && millis() - lastRaw >= 50) {  // Arduino serial plotter friendly
    lastRaw = millis();
    Serial.printf("pulse:%ld g:%.3f\n", ppgRaw(), lastG);
  }
}

float batteryVolts() { return analogReadMilliVolts(PIN_BATTERY) * BATTERY_DIVIDER / 1000.0f; }

// Build one reading and reset the window counters. Returns the JSON length.
size_t buildReading(char* out, size_t cap, int rssi) {
  JsonDocument doc;
  doc["animal_id"] = cfg.id;
  int32_t hr, spo2;
  bool hrOk, spo2Ok;
  ppgResult(hr, hrOk, spo2, spo2Ok);
  if (hrOk) doc["hr"] = hr;
  else doc["hr"] = nullptr;
  if (spo2Ok) doc["spo2"] = spo2;
  else doc["spo2"] = nullptr;
  doc["body_temp"] = nullptr;
  if (haveThermo) {
    float t = thermo.getTempCByIndex(0);  // conversion requested at the previous reading
    if (t != DEVICE_DISCONNECTED_C && t > 25 && t < 45) doc["body_temp"] = roundf(t * 100) / 100;
    thermo.requestTemperatures();
  }
  if (act.n) doc["activity"] = roundf(act.mean() * 10000) / 10000;
  else doc["activity"] = nullptr;
  if (haveImu) doc["steps"] = act.steps;
  else doc["steps"] = nullptr;
  if (cfg.battery) doc["battery"] = roundf(batteryVolts() * 1000) / 1000;
  else doc["battery"] = nullptr;
  if (rssi) doc["rssi"] = rssi;
  act.reset();
  return serializeJson(doc, out, cap);
}

// ---------------------------------------------------------------- Wi-Fi + MQTT
#if !defined(LMS_MODE_ESPNOW)
uint32_t lastWifiTry = 0, lastMqttTry = 0;
bool wifiStarted = false, wifiAnnounced = false;

void startWifi() {
  if (cfg.ssid.isEmpty()) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
  wifiStarted = true;
  lastWifiTry = millis();
  Serial.printf("wifi: connecting to \"%s\"\n", cfg.ssid.c_str());
}

bool connectMqtt() {
  if (mqtt.connected()) return true;
  String id = "lms-collar-" + cfg.id;
  bool ok = mqtt.connect(id.c_str(), cfg.mqttUser.c_str(), cfg.mqttPass.c_str());
  Serial.printf("mqtt %s:%u %s", cfg.mqttHost.c_str(), cfg.mqttPort, ok ? "connected\n" : "failed");
  if (!ok) Serial.printf(" rc=%d (4/5 = wrong user/password, -2 = host unreachable or port 1883 blocked)\n",
                         mqtt.state());
  return ok;
}

// Non-blocking: keeps sampling the sensors while Wi-Fi comes and goes.
void maintainNet() {
  if (cfg.ssid.isEmpty()) return;
  if (WiFi.status() != WL_CONNECTED) {
    wifiAnnounced = false;
    if (!wifiStarted || millis() - lastWifiTry > 20000) startWifi();
    return;
  }
  if (!wifiAnnounced) {
    wifiAnnounced = true;
    Serial.printf("wifi: connected, ip %s, rssi %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }
  if (!mqtt.connected() && millis() - lastMqttTry > 5000) {
    lastMqttTry = millis();
    connectMqtt();
  }
  mqtt.loop();
}

bool waitForNet(uint32_t timeoutMs) {
  startWifi();
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeoutMs) {
    sampleAll();
    delay(5);
  }
  return WiFi.status() == WL_CONNECTED && connectMqtt();
}

void sendReading() {
  char payload[256];
  size_t n = buildReading(payload, sizeof(payload), WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0);
  Serial.println(payload);  // USB serial copy (backup path via barn/serial_bridge.py)
  if (mqtt.connected()) mqtt.publish(topic.c_str(), (const uint8_t*)payload, n, false);
}
#endif

// ---------------------------------------------------------------- ESP-NOW
#if defined(LMS_MODE_ESPNOW)
volatile bool sendDone = false;
bool espnowReady = false;
esp_now_peer_info_t peer = {};

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onSent(const wifi_tx_info_t*, esp_now_send_status_t status) {
#else
void onSent(const uint8_t*, esp_now_send_status_t status) {
#endif
  sendDone = true;
}

void startEspNow() {
  if (espnowReady) return;
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("esp-now init failed");
    return;
  }
  esp_now_register_send_cb(onSent);
  memset(peer.peer_addr, 0xFF, 6);  // broadcast: the gateway listens to everyone on the channel
  peer.channel = ESPNOW_CHANNEL;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  espnowReady = true;
}

void sendReading() {
  startEspNow();
  char payload[250];  // ESP-NOW frames carry at most 250 bytes
  size_t n = buildReading(payload, sizeof(payload), 0);
  Serial.println(payload);
  if (!espnowReady) return;
  sendDone = false;
  esp_now_send(peer.peer_addr, (const uint8_t*)payload, n);
  uint32_t t0 = millis();
  while (!sendDone && millis() - t0 < 200) delay(5);
}
#endif

// ---------------------------------------------------------------- status for `show`
void printStatus() {
  Serial.printf("mode=%s ppg running=%s imu=%s ds18b20=%s", MODE_NAME, ppgName(ppg), haveImu ? "yes" : "no",
                haveThermo ? "yes" : "no");
#if !defined(LMS_MODE_ESPNOW)
  Serial.printf(" wifi=%s mqtt=%s", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "down",
                mqtt.connected() ? "up" : "down");
#else
  Serial.printf(" espnow channel=%d mac=%s", ESPNOW_CHANNEL, WiFi.macAddress().c_str());
#endif
  Serial.println();
}

// ---------------------------------------------------------------- sleep modes
#if defined(LMS_MODE_WIFI_SLEEP) || defined(LMS_MODE_ESPNOW)
void measureWindow() {
  uint32_t t0 = millis();
  while (millis() - t0 < MEASURE_MS) {
    sampleAll();
    delay(2);
  }
}

void goToSleep() {
  ppgSleep();
  imu.sleep();
  WiFi.mode(WIFI_OFF);
  Serial.printf("sleeping %d s (type a command within %d s of waking to stay awake)\n", SLEEP_SECONDS,
                MEASURE_MS / 1000);
  Serial.flush();
  esp_deep_sleep((uint64_t)SLEEP_SECONDS * 1000000ULL);
}
#endif

void setup() {
  Serial.begin(115200);
  delay(200);
  wakeCount++;
  settingsLoad();
  setupSensors();
#if !defined(LMS_MODE_ESPNOW)
  topic = "lms/collar/" + cfg.id + "/vitals";
  mqtt.setServer(cfg.mqttHost.c_str(), cfg.mqttPort);
  if (cfg.ssid.isEmpty()) Serial.println("no Wi-Fi set: readings go to USB serial only (type help)");
#endif

#if defined(LMS_MODE_WIFI_SLEEP)
  measureWindow();  // radio off while measuring
  if (!settingsTouched()) {
    if (waitForNet(8000)) {
      sendReading();
      mqtt.loop();
      delay(50);  // let the TCP send finish before cutting power
      mqtt.disconnect();
    } else {
      sendReading();  // serial copy only
    }
    goToSleep();
  }
#elif defined(LMS_MODE_ESPNOW)
  measureWindow();
  if (!settingsTouched()) {
    sendReading();
    goToSleep();
  }
#else
  startWifi();
#endif
  lastReport = millis();
  Serial.println("ready (type help for commands)");
}

// Always-on loop: mode wifi, or a sleep mode kept awake by a serial command.
void loop() {
  sampleAll();
#if !defined(LMS_MODE_ESPNOW)
  maintainNet();
#endif
  if (millis() - lastReport >= REPORT_SECONDS * 1000UL && ppgReady()) {
    lastReport = millis();
    sendReading();
  }
}
