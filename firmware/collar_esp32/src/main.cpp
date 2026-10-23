// LMS cattle collar firmware.
//
// Every REPORT_SECONDS it publishes one JSON message to lms/collar/<ANIMAL_ID>/vitals
// matching common/schemas.py VitalsMsg:
//   {"hr": 68, "spo2": 97, "body_temp": 38.6, "activity": 0.041, "steps": 3, "battery": 3.91, "rssi": -61}
// A sensor that is missing or has no valid reading sends null - never a made-up value.
// No timestamp: the collar has no clock, so ingest stamps the receive time.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <DallasTemperature.h>
#include <MPU6050.h>
#include <OneWire.h>
#include <PubSubClient.h>
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

// ---------- sensors ----------
MAX30105 pulse;
MPU6050 imu;
OneWire oneWire(PIN_ONEWIRE);
DallasTemperature thermo(&oneWire);
WiFiClient net;
PubSubClient mqtt(net);

bool havePulse = false, haveImu = false, haveThermo = false;

// MAX30102 samples for the Maxim SpO2/HR algorithm (25 samples/s, 4 s window)
const int32_t PULSE_BUF = 100;
uint32_t irBuf[PULSE_BUF], redBuf[PULSE_BUF];
int32_t pulseIdx = 0;
bool pulseFull = false;

// activity: mean |acceleration| - 1 g over the report window, and a simple step counter
const float ACC_LSB_PER_G = 16384.0f;  // +-2 g range
double actSum = 0;
uint32_t actN = 0;
uint32_t steps = 0;
bool stepHigh = false;
uint32_t lastStepMs = 0;
const float STEP_HIGH_G = 1.25f, STEP_LOW_G = 1.05f;
const uint32_t STEP_MIN_MS = 350;

uint32_t lastReport = 0, lastImu = 0;
char topic[64];

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(250);
  Serial.printf("wifi %s\n", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "FAILED");
}

void connectMqtt() {
  if (mqtt.connected() || WiFi.status() != WL_CONNECTED) return;
  String id = String("lms-collar-") + ANIMAL_ID;
  if (mqtt.connect(id.c_str(), MQTT_USER, MQTT_PASSWORD)) {
    Serial.println("mqtt connected");
  } else {
    Serial.printf("mqtt failed rc=%d\n", mqtt.state());
  }
}

float batteryVolts() {
  uint32_t mv = analogReadMilliVolts(PIN_BATTERY);
  return mv * BATTERY_DIVIDER / 1000.0f;
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

void report() {
  JsonDocument doc;
  doc["hr"] = nullptr;
  doc["spo2"] = nullptr;
  if (havePulse && pulseFull) {
    // the algorithm wants the buffer in time order starting at the oldest sample
    uint32_t ir[PULSE_BUF], red[PULSE_BUF];
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
  doc["rssi"] = WiFi.RSSI();

  char payload[256];
  size_t n = serializeJson(doc, payload, sizeof(payload));
  Serial.println(payload);
  if (mqtt.connected()) mqtt.publish(topic, (const uint8_t*)payload, n, false);

  actSum = 0;
  actN = 0;
  steps = 0;
}

void setup() {
  Serial.begin(115200);
  delay(200);
  snprintf(topic, sizeof(topic), "lms/collar/%s/vitals", ANIMAL_ID);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);

  havePulse = pulse.begin(Wire, I2C_SPEED_FAST);
  if (havePulse) {
    // LED 0x1F, average 4, red+IR, 100 sps / 4 = 25 effective sps, pulse width 411, ADC range 4096
    pulse.setup(0x1F, 4, 2, 100, 411, 4096);
  }
  imu.initialize();
  haveImu = imu.testConnection();
  if (haveImu) imu.setFullScaleAccelRange(MPU6050_ACCEL_FS_2);
  thermo.begin();
  haveThermo = thermo.getDeviceCount() > 0;
  analogSetPinAttenuation(PIN_BATTERY, ADC_11db);
  Serial.printf("collar %s  max30102:%d mpu6050:%d ds18b20:%d\n", ANIMAL_ID, havePulse, haveImu, haveThermo);

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  connectWifi();
  connectMqtt();
}

void loop() {
  samplePulse();
  sampleImu();
  if (millis() - lastReport >= REPORT_SECONDS * 1000UL) {
    lastReport = millis();
    connectWifi();
    connectMqtt();
    report();
  }
  mqtt.loop();
}
