// UNO prototype collar: prints one JSON line every ~4 s (one full pulse window), e.g.
//   {"animal_id":"C001","hr":71,"spo2":97,"activity":0.0412,"steps":3}
// Fields with no valid reading are null (no substitute values).
// Wiring: MAX30102 and MPU6050 both on SDA=A4, SCL=A5, 3.3V/5V per module, common GND.

#include <Arduino.h>
#include <MPU6050.h>
#include <Wire.h>

#include "MAX30105.h"
#include "spo2_algorithm.h"

#define ANIMAL_ID "C001"
const unsigned long REPORT_MS = 5000;  // used only when the MAX30102 is missing

MAX30105 pulse;
MPU6050 imu;
bool havePulse = false, haveImu = false;

// UNO has 2 KB RAM and the SpO2 algorithm itself needs ~800 B, so the sample buffers are
// 16-bit and filled linearly (no ring buffer, no copies): 100 samples at 25/s = one 4 s window.
const int32_t BUF = 100;
uint16_t irBuf[BUF], redBuf[BUF];
int32_t idx = 0;

float actSum = 0;
unsigned long actN = 0, steps = 0, lastImu = 0, lastStep = 0, lastReport = 0;
bool stepHigh = false;

void setup() {
  Serial.begin(115200);
  Wire.begin();
  havePulse = pulse.begin(Wire, I2C_SPEED_FAST);
  if (havePulse) pulse.setup(0x1F, 4, 2, 100, 411, 4096);
  imu.initialize();
  haveImu = imu.testConnection();
  Serial.print(F("{\"status\":\"ready\",\"max30102\":"));
  Serial.print(havePulse ? F("true") : F("false"));
  Serial.print(F(",\"mpu6050\":"));
  Serial.print(haveImu ? F("true") : F("false"));
  Serial.println(F("}"));
}

void printNumOrNull(const __FlashStringHelper* key, bool valid, float v, int digits) {
  Serial.print(key);
  if (valid) Serial.print(v, digits);
  else Serial.print(F("null"));
}

void loop() {
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
  if (haveImu && millis() - lastImu >= 20) {
    lastImu = millis();
    int16_t ax, ay, az;
    imu.getAcceleration(&ax, &ay, &az);
    float g = sqrt((float)ax * ax + (float)ay * ay + (float)az * az) / 16384.0;
    actSum += fabs(g - 1.0);
    actN++;
    if (!stepHigh && g > 1.25 && millis() - lastStep > 350) {
      stepHigh = true;
      steps++;
      lastStep = millis();
    } else if (stepHigh && g < 1.05) {
      stepHigh = false;
    }
  }
  // report when a pulse window is full (or on a timer if there is no pulse sensor)
  if (havePulse ? idx < BUF : millis() - lastReport < REPORT_MS) return;
  lastReport = millis();

  int32_t spo2 = 0, hr = 0;
  int8_t spo2Ok = 0, hrOk = 0;
  bool contact = false;
  if (havePulse) {
    maxim_heart_rate_and_oxygen_saturation(irBuf, BUF, redBuf, &spo2, &spo2Ok, &hr, &hrOk);
    contact = irBuf[BUF - 1] > 20000;
    idx = 0;
  }
  Serial.print(F("{\"animal_id\":\"" ANIMAL_ID "\""));
  printNumOrNull(F(",\"hr\":"), contact && hrOk && hr > 20 && hr < 250, hr, 0);
  printNumOrNull(F(",\"spo2\":"), contact && spo2Ok && spo2 > 50 && spo2 <= 100, spo2, 0);
  printNumOrNull(F(",\"activity\":"), actN > 0, actN ? actSum / actN : 0, 4);
  printNumOrNull(F(",\"steps\":"), haveImu, steps, 0);
  Serial.println(F("}"));
  actSum = 0;
  actN = 0;
  steps = 0;
}
