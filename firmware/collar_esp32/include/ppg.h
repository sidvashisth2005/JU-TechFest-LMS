// One interface over the four pulse (PPG) sensors the collar can use. Which board we get
// is not known in advance, so all four are compiled in and the I2C ones are detected.
#pragma once
#include <Arduino.h>

enum PpgKind : int8_t {
  PPG_AUTO = -1,
  PPG_NONE = 0,
  PPG_MAX30102 = 1,  // generic MAX30102/MAX30105 breakout (SparkFun library + Maxim algorithm)
  PPG_MAX30100 = 2,  // older MAX30100 module (oxullo library)
  PPG_DFROBOT = 3,   // DFRobot Gravity SEN0344 (has its own MCU; DFRobot library)
  PPG_ANALOG = 4,    // analog "Pulse Sensor": heart rate only
};

const char* ppgName(int8_t kind);
int8_t ppgFromName(const String& name);  // -2 if unknown
uint8_t ppgPartId();                     // register 0xFF of the device at 0x57, 0 if none

PpgKind ppgBegin(int8_t wanted);  // PPG_AUTO detects; returns what is actually running
void ppgSample();                 // call as often as possible
bool ppgReady();                  // enough samples for a reading
// hrOk/spo2Ok false = no trustworthy value (no contact, too noisy, sensor lacks it)
void ppgResult(int32_t& hr, bool& hrOk, int32_t& spo2, bool& spo2Ok);
long ppgRaw();  // latest raw signal for the `raw` command, -1 if the sensor doesn't expose it
void ppgSleep();
