#include "ppg.h"

#include <LmsBeat.h>
#include <Wire.h>

#include "DFRobot_BloodOxygen_S.h"
#include "MAX30100_PulseOximeter.h"
#include "MAX30105.h"
#include "config.h"
#include "spo2_algorithm.h"  // last: it defines min() and BUFFER_SIZE macros

static PpgKind running = PPG_NONE;

// MAX30102: 25 samples/s, 4 s window for the Maxim SpO2/HR algorithm
static MAX30105 max102;
static const int32_t BUF = 100;
static uint32_t irBuf[BUF], redBuf[BUF];
static int32_t idx = 0;
static bool full = false;

// MAX30100: the library does beat detection itself; update() must run every few ms
static PulseOximeter pox;

// DFRobot SEN0344: its own MCU computes HR/SpO2 over a 4 s window; we poll it
static DFRobot_BloodOxygen_S_I2C dfr(&Wire, 0x57);
static uint32_t dfrLast = 0;
static int dfrHr = -1, dfrSpo2 = -1;

// analog pulse sensor
static LmsBeat beat;
static uint32_t anaLast = 0;
static int anaRaw = 0;

const char* ppgName(int8_t k) {
  switch (k) {
    case PPG_AUTO: return "auto";
    case PPG_MAX30102: return "max30102";
    case PPG_MAX30100: return "max30100";
    case PPG_DFROBOT: return "dfrobot";
    case PPG_ANALOG: return "analog";
    default: return "none";
  }
}

int8_t ppgFromName(const String& n) {
  for (int8_t k = PPG_AUTO; k <= PPG_ANALOG; k++)
    if (n.equalsIgnoreCase(ppgName(k))) return k;
  return -2;
}

static bool present(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

uint8_t ppgPartId() {
  Wire.beginTransmission(0x57);
  Wire.write(0xFF);  // PART_ID: 0x15 on MAX30102/MAX30105, 0x11 on MAX30100
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom((uint8_t)0x57, (uint8_t)1) != 1) return 0;
  return Wire.read();
}

PpgKind ppgBegin(int8_t wanted) {
  int8_t k = wanted;
  if (k == PPG_AUTO) {
    uint8_t id = ppgPartId();
    if (id == 0x15) k = PPG_MAX30102;
    else if (id == 0x11) k = PPG_MAX30100;
    else if (present(0x57)) k = PPG_DFROBOT;  // answers at 0x57 but is not a bare Maxim chip
    else k = PPG_NONE;
  }
  bool ok = false;
  switch (k) {
    case PPG_MAX30102:
      ok = max102.begin(Wire, I2C_SPEED_FAST);
      // LED 0x1F, average 4, red+IR, 100 sps / 4 = 25 effective sps, pulse width 411, ADC range 4096
      if (ok) max102.setup(0x1F, 4, 2, 100, 411, 4096);
      break;
    case PPG_MAX30100:
      ok = pox.begin();
      break;
    case PPG_DFROBOT:
      ok = dfr.begin();
      if (ok) dfr.sensorStartCollect();
      break;
    case PPG_ANALOG:
      analogSetPinAttenuation(PIN_PULSE_ANALOG, ADC_11db);
      beat.begin(4095);
      ok = true;  // an analog pin can't tell us whether a sensor is attached
      break;
    default:
      break;
  }
  running = ok ? (PpgKind)k : PPG_NONE;
  return running;
}

void ppgSample() {
  switch (running) {
    case PPG_MAX30102:
      max102.check();
      while (max102.available()) {
        redBuf[idx] = max102.getFIFORed();
        irBuf[idx] = max102.getFIFOIR();
        max102.nextSample();
        if (++idx >= BUF) {
          idx = 0;
          full = true;
        }
      }
      break;
    case PPG_MAX30100:
      pox.update();
      break;
    case PPG_DFROBOT:
      if (millis() - dfrLast >= 1000) {
        dfrLast = millis();
        dfr.getHeartbeatSPO2();
        dfrHr = dfr._sHeartbeatSPO2.Heartbeat;
        dfrSpo2 = dfr._sHeartbeatSPO2.SPO2;
      }
      break;
    case PPG_ANALOG:
      if (millis() - anaLast >= 10) {
        anaLast = millis();
        anaRaw = analogRead(PIN_PULSE_ANALOG);
        beat.add(anaRaw, anaLast);
      }
      break;
    default:
      break;
  }
}

bool ppgReady() { return running != PPG_MAX30102 || full; }

void ppgResult(int32_t& hr, bool& hrOk, int32_t& spo2, bool& spo2Ok) {
  hr = spo2 = 0;
  hrOk = spo2Ok = false;
  switch (running) {
    case PPG_MAX30102: {
      if (!full) return;
      // the algorithm wants the buffer in time order starting at the oldest sample
      static uint32_t ir[BUF], red[BUF];
      for (int32_t i = 0; i < BUF; i++) {
        ir[i] = irBuf[(idx + i) % BUF];
        red[i] = redBuf[(idx + i) % BUF];
      }
      int8_t hv, sv;
      maxim_heart_rate_and_oxygen_saturation(ir, BUF, red, &spo2, &sv, &hr, &hv);
      bool contact = ir[BUF - 1] > 50000;  // no skin contact -> weak IR
      hrOk = contact && hv && hr > 20 && hr < 250;
      spo2Ok = contact && sv && spo2 > 50 && spo2 <= 100;
      break;
    }
    case PPG_MAX30100: {
      float h = pox.getHeartRate();
      uint8_t s = pox.getSpO2();
      hr = lroundf(h);
      spo2 = s;
      hrOk = h > 20 && h < 250;
      spo2Ok = s > 50 && s <= 100;
      break;
    }
    case PPG_DFROBOT:
      hr = dfrHr;
      spo2 = dfrSpo2;
      hrOk = hr > 20 && hr < 250;  // the module reports -1 without a finger
      spo2Ok = spo2 > 50 && spo2 <= 100;
      break;
    case PPG_ANALOG:
      hr = beat.bpm(millis());
      hrOk = hr > 20 && hr < 250;
      break;
    default:
      break;
  }
}

long ppgRaw() {
  switch (running) {
    case PPG_MAX30102: return irBuf[(idx + BUF - 1) % BUF];
    case PPG_ANALOG: return anaRaw;
    default: return -1;
  }
}

void ppgSleep() {
  switch (running) {
    case PPG_MAX30102: max102.shutDown(); break;
    case PPG_MAX30100: pox.shutdown(); break;
    case PPG_DFROBOT: dfr.sensorEndCollect(); break;
    default: break;
  }
}
