// Collar settings kept in flash (NVS) and changed over USB serial, so a collar can be moved
// to a new Wi-Fi or laptop IP on the day without recompiling. Type `help` in the monitor.
#pragma once
#include <Arduino.h>

struct Settings {
  String id, ssid, pass, mqttHost, mqttUser, mqttPass;
  uint16_t mqttPort;
  int8_t ppg;    // PpgKind
  bool battery;  // battery divider wired to PIN_BATTERY
};

extern Settings cfg;
extern bool rawMode;  // `raw` command: stream raw sensor values for wiring checks

void settingsLoad();
void settingsPoll();     // read and run serial commands; call from every loop
bool settingsTouched();  // a command arrived since boot (sleep modes then stay awake)
void printStatus();      // implemented in main.cpp, used by `show`
void i2cScan();          // `scan`: list I2C devices and name the known ones
