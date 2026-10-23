// Minimal MPU6050-family accelerometer reader, shared by the ESP32 collar and the UNO backup.
//
// Talks to the registers directly instead of using a library, because cheap "MPU6050" boards
// are often MPU6500/MPU9250 clones: same accelerometer registers, but a different WHO_AM_I,
// so library connection checks reject them. Any chip that answers at 0x68 or 0x69 is used.
#pragma once
#include <Arduino.h>
#include <Wire.h>

class LmsImu {
 public:
  uint8_t addr = 0;    // 0x68 or 0x69 (AD0 high); 0 = not found
  uint8_t whoami = 0;  // 0x68 MPU6050, 0x70 MPU6500, 0x71/0x73 MPU9250/9255, 0x98/0x72 clones

  bool begin(TwoWire& w = Wire) {
    wire = &w;
    const uint8_t candidates[2] = {0x68, 0x69};
    for (uint8_t i = 0; i < 2 && !addr; i++) {
      uint8_t id;
      if (readReg(candidates[i], 0x75, id) && id != 0x00 && id != 0xFF) {
        addr = candidates[i];
        whoami = id;
      }
    }
    if (!addr) return false;
    writeReg(0x6B, 0x00);  // PWR_MGMT_1: wake up, internal clock
    delay(10);
    writeReg(0x1C, 0x00);  // ACCEL_CONFIG: +-2 g (16384 LSB/g)
    return true;
  }

  // Acceleration magnitude in g (1.0 when still). False if the read failed.
  bool readG(float& g) {
    if (!addr) return false;
    wire->beginTransmission(addr);
    wire->write(0x3B);  // ACCEL_XOUT_H
    if (wire->endTransmission(false) != 0) return false;
    if (wire->requestFrom(addr, (uint8_t)6) != 6) return false;
    int16_t v[3];
    for (uint8_t i = 0; i < 3; i++) {
      uint8_t hi = wire->read(), lo = wire->read();
      v[i] = (int16_t)((hi << 8) | lo);
    }
    g = sqrt((float)v[0] * v[0] + (float)v[1] * v[1] + (float)v[2] * v[2]) / 16384.0f;
    return true;
  }

  void sleep() {
    if (addr) writeReg(0x6B, 0x40);
  }

 private:
  TwoWire* wire = &Wire;

  bool readReg(uint8_t a, uint8_t reg, uint8_t& out) {
    wire->beginTransmission(a);
    wire->write(reg);
    if (wire->endTransmission(false) != 0) return false;
    if (wire->requestFrom(a, (uint8_t)1) != 1) return false;
    out = wire->read();
    return true;
  }

  void writeReg(uint8_t reg, uint8_t val) {
    wire->beginTransmission(addr);
    wire->write(reg);
    wire->write(val);
    wire->endTransmission();
  }
};

// Activity and steps from the acceleration magnitude, same rules on both boards.
// activity = mean |g - 1| over the reporting window; a step = a peak above 1.25 g after
// dropping below 1.05 g, at most one every 350 ms.
struct LmsActivity {
  float sum = 0;
  uint32_t n = 0, steps = 0, lastStepMs = 0;
  bool high = false;

  void add(float g, uint32_t ms) {
    sum += fabs(g - 1.0f);
    n++;
    if (!high && g > 1.25f && ms - lastStepMs > 350) {
      high = true;
      steps++;
      lastStepMs = ms;
    } else if (high && g < 1.05f) {
      high = false;
    }
  }
  float mean() const { return n ? sum / n : 0; }
  void reset() {
    sum = 0;
    n = 0;
    steps = 0;
  }
};
