// UNO backup collar: no radio, so it sends readings over the USB cable. Prints one JSON line
// per reading, e.g.
//   {"animal_id":"C001","hr":71,"spo2":97,"body_temp":null,"activity":0.0412,"steps":3}
// and barn/serial_bridge.py (on the laptop or the Pi) forwards each line to MQTT.
// Fields with no valid reading are null (no substitute values).
//
// The UNO has 2 KB of RAM, so only one pulse sensor driver fits per build. Pick the env that
// matches the board (see platformio.ini): uno (MAX30102), uno_max30100, uno_dfrobot, uno_analog.
// Wiring: pulse sensor + MPU6050 on SDA=A4, SCL=A5, VCC (3.3V/5V per module), common GND.
// Analog pulse sensor signal -> A0. DS18B20 (builds with WITH_DS18B20) data -> D2, 4.7k to 5V.

#include <Arduino.h>
#include <LmsImu.h>
#include <Wire.h>

#if defined(PPG_MAX30100)
#include "MAX30100_PulseOximeter.h"
#define PPG_NAME "max30100"
PulseOximeter pox;
#elif defined(PPG_DFROBOT)
#include "DFRobot_BloodOxygen_S.h"
#define PPG_NAME "dfrobot"
DFRobot_BloodOxygen_S_I2C dfr(&Wire, 0x57);
#elif defined(PPG_ANALOG)
#include <LmsBeat.h>
#define PPG_NAME "analog"
LmsBeat beat;
unsigned long lastAnalog = 0;
#else
#define PPG_MAX30102
#define PPG_NAME "max30102"
#include "MAX30105.h"
#include "spo2_algorithm.h"
MAX30105 pulse;
// The SpO2 algorithm itself needs ~800 B, so the sample buffers are 16-bit and filled
// linearly (no ring buffer, no copies): 100 samples at 25/s = one 4 s window.
const int32_t BUF = 100;
uint16_t irBuf[BUF], redBuf[BUF];
int32_t idx = 0;
#endif

#ifdef WITH_DS18B20
#include <DallasTemperature.h>
#include <OneWire.h>
OneWire oneWire(2);
DallasTemperature thermo(&oneWire);
bool haveThermo = false;
#endif

#ifndef ANIMAL_ID
#define ANIMAL_ID "C001"
#endif
const unsigned long REPORT_MS = 4000;  // reading period when the sensor isn't window-based

LmsImu imu;
LmsActivity act;
bool havePulse = false, haveImu = false;
unsigned long lastImu = 0, lastReport = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin();
#if defined(PPG_MAX30100)
  havePulse = pox.begin();
#elif defined(PPG_DFROBOT)
  havePulse = dfr.begin();
  if (havePulse) dfr.sensorStartCollect();
#elif defined(PPG_ANALOG)
  beat.begin(1023);
  havePulse = true;  // an analog pin can't tell whether a sensor is attached
#else
  havePulse = pulse.begin(Wire, I2C_SPEED_FAST);
  if (havePulse) pulse.setup(0x1F, 4, 2, 100, 411, 4096);
#endif
  haveImu = imu.begin(Wire);
#ifdef WITH_DS18B20
  thermo.begin();
  haveThermo = thermo.getDeviceCount() > 0;
  if (haveThermo) {
    thermo.setWaitForConversion(false);
    thermo.requestTemperatures();
  }
#endif
  Serial.print(F("{\"status\":\"ready\",\"ppg\":\"" PPG_NAME "\",\"ppg_ok\":"));
  Serial.print(havePulse ? F("true") : F("false"));
  Serial.print(F(",\"imu\":"));
  Serial.print(haveImu ? F("true") : F("false"));
  Serial.print(F(",\"imu_id\":"));
  Serial.print(imu.whoami);
  Serial.println(F("}"));
}

void printNumOrNull(const __FlashStringHelper* key, bool valid, float v, int digits) {
  Serial.print(key);
  if (valid) Serial.print(v, digits);
  else Serial.print(F("null"));
}

void loop() {
  // ---- sample
#if defined(PPG_MAX30100)
  if (havePulse) pox.update();  // must run every few ms
#elif defined(PPG_ANALOG)
  if (millis() - lastAnalog >= 10) {
    lastAnalog = millis();
    beat.add(analogRead(A0), lastAnalog);
  }
#elif defined(PPG_MAX30102)
  if (havePulse) {
    pulse.check();
    while (pulse.available()) {
      if (idx < BUF) {
        redBuf[idx] = (uint16_t)min(pulse.getFIFORed(), (uint32_t)65535);
        irBuf[idx] = (uint16_t)min(pulse.getFIFOIR(), (uint32_t)65535);
        idx++;
      }
      pulse.nextSample();
    }
  }
#endif
  if (haveImu && millis() - lastImu >= 20) {
    lastImu = millis();
    float g;
    if (imu.readG(g)) act.add(g, lastImu);
  }

  // ---- report when a MAX30102 window is full, otherwise on a timer
#if defined(PPG_MAX30102)
  if (havePulse ? idx < BUF : millis() - lastReport < REPORT_MS) return;
#else
  if (millis() - lastReport < REPORT_MS) return;
#endif
  lastReport = millis();

  long hr = 0, spo2 = 0;
  bool hrOk = false, spo2Ok = false;
#if defined(PPG_MAX30100)
  hr = lround(pox.getHeartRate());
  spo2 = pox.getSpO2();
  hrOk = havePulse && hr > 20 && hr < 250;
  spo2Ok = havePulse && spo2 > 50 && spo2 <= 100;
#elif defined(PPG_DFROBOT)
  if (havePulse) {
    dfr.getHeartbeatSPO2();
    hr = dfr._sHeartbeatSPO2.Heartbeat;  // -1 without a finger
    spo2 = dfr._sHeartbeatSPO2.SPO2;
    hrOk = hr > 20 && hr < 250;
    spo2Ok = spo2 > 50 && spo2 <= 100;
  }
#elif defined(PPG_ANALOG)
  hr = beat.bpm(millis());
  hrOk = hr > 20 && hr < 250;
#else
  if (havePulse) {
    int32_t s = 0, h = 0;
    int8_t sv = 0, hv = 0;
    maxim_heart_rate_and_oxygen_saturation(irBuf, BUF, redBuf, &s, &sv, &h, &hv);
    bool contact = irBuf[BUF - 1] > 20000;  // no skin contact -> weak IR
    hr = h;
    spo2 = s;
    hrOk = contact && hv && h > 20 && h < 250;
    spo2Ok = contact && sv && s > 50 && s <= 100;
    idx = 0;
  }
#endif

  Serial.print(F("{\"animal_id\":\"" ANIMAL_ID "\""));
  printNumOrNull(F(",\"hr\":"), hrOk, hr, 0);
  printNumOrNull(F(",\"spo2\":"), spo2Ok, spo2, 0);
#ifdef WITH_DS18B20
  float t = haveThermo ? thermo.getTempCByIndex(0) : DEVICE_DISCONNECTED_C;
  printNumOrNull(F(",\"body_temp\":"), t > 25 && t < 45, t, 2);
  if (haveThermo) thermo.requestTemperatures();
#endif
  printNumOrNull(F(",\"activity\":"), act.n > 0, act.mean(), 4);
  printNumOrNull(F(",\"steps\":"), haveImu, act.steps, 0);
  Serial.println(F("}"));
  act.reset();
}
