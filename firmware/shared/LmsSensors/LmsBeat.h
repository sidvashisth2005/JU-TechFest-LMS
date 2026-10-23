// Heart rate from an analog pulse sensor (the green "Pulse Sensor" / KY-039 style PPG that
// outputs a voltage). Only heart rate: these sensors have one LED colour, so no SpO2.
//
// Feed it ~100 samples/s. It follows the signal's top and bottom (an envelope that slowly
// relaxes), calls a beat when the signal rises through 60% of that range, and re-arms below
// 40%. Heart rate = 60000 / median of the last 5 beat-to-beat intervals. No beats for 3 s,
// or a range too small to be a pulse, means "no reading" (-1), never a guessed number.
#pragma once
#include <Arduino.h>

class LmsBeat {
 public:
  void begin(int fullScale) {
    minAmp = fullScale / 50.0f;  // ~2% of the ADC range; below that it's noise, not a pulse
    started = false;
    count = 0;
    lastBeat = 0;
  }

  void add(int raw, uint32_t ms) {
    if (!started) {
      s = hi = lo = raw;
      started = true;
      return;
    }
    s += (raw - s) * 0.3f;  // light smoothing
    if (s > hi) hi = s;
    else hi -= (hi - s) * 0.02f;
    if (s < lo) lo = s;
    else lo += (s - lo) * 0.02f;
    float amp = hi - lo;
    if (amp < minAmp) {
      armed = true;
      return;
    }
    if (armed && s > lo + 0.6f * amp && ms - lastBeat > 300) {  // max 200 bpm
      armed = false;
      if (lastBeat && ms - lastBeat < 2000) {  // min 30 bpm
        ibi[pos] = ms - lastBeat;
        pos = (pos + 1) % N;
        if (count < N) count++;
      }
      lastBeat = ms;
    } else if (!armed && s < lo + 0.4f * amp) {
      armed = true;
    }
  }

  // Beats per minute, or -1 when there is no trustworthy reading.
  int bpm(uint32_t now) const {
    if (count < 3 || now - lastBeat > 3000) return -1;
    uint32_t v[N];
    for (uint8_t i = 0; i < count; i++) v[i] = ibi[i];
    for (uint8_t i = 1; i < count; i++)  // insertion sort, at most 5 values
      for (uint8_t j = i; j > 0 && v[j - 1] > v[j]; j--) {
        uint32_t t = v[j];
        v[j] = v[j - 1];
        v[j - 1] = t;
      }
    return (int)(60000UL / v[count / 2]);
  }

 private:
  static const uint8_t N = 5;
  float s = 0, hi = 0, lo = 0, minAmp = 20;
  bool started = false, armed = true;
  uint32_t lastBeat = 0, ibi[N] = {0};
  uint8_t pos = 0, count = 0;
};
