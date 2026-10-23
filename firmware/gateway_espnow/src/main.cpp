// ESP-NOW -> USB serial gateway for LMS collars.
//
// Prints every valid collar reading as one JSON line, e.g.
//   {"animal_id":"C001","hr":68,"spo2":97,"body_temp":38.6,"activity":0.041,"steps":3,"battery":3.91,"rssi":-58}
// The radio signal strength of the received frame is added as "rssi" (useful to see collar range).
// Anything that is not a JSON object is dropped.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#ifndef ESPNOW_CHANNEL
#define ESPNOW_CHANNEL 1
#endif

static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static char pending[260];
static volatile int pendingLen = 0;
static volatile int pendingRssi = 0;
static volatile uint32_t dropped = 0;

// Runs in the Wi-Fi task: copy the frame out and let loop() print it.
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  int rssi = info->rx_ctrl ? info->rx_ctrl->rssi : 0;
#else
void onRecv(const uint8_t* mac, const uint8_t* data, int len) {
  int rssi = 0;
#endif
  if (len <= 2 || len > 250 || data[0] != '{' || data[len - 1] != '}') return;
  portENTER_CRITICAL(&lock);
  if (pendingLen == 0) {
    memcpy(pending, data, len);
    pendingLen = len;
    pendingRssi = rssi;
  } else {
    dropped++;  // loop() hasn't printed the previous one yet
  }
  portEXIT_CRITICAL(&lock);
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("{\"error\":\"esp-now init failed\"}");
    return;
  }
  esp_now_register_recv_cb(onRecv);
  Serial.printf("{\"status\":\"gateway ready\",\"channel\":%d,\"mac\":\"%s\"}\n", ESPNOW_CHANNEL,
                WiFi.macAddress().c_str());
}

void loop() {
  char line[300];
  int len = 0, rssi = 0;
  portENTER_CRITICAL(&lock);
  if (pendingLen) {
    len = pendingLen;
    rssi = pendingRssi;
    memcpy(line, pending, len);
    pendingLen = 0;
  }
  portEXIT_CRITICAL(&lock);
  if (len) {
    line[len - 1] = '\0';  // drop the closing brace so the radio RSSI can be appended
    if (rssi) Serial.printf("%s,\"rssi\":%d}\n", line, rssi);
    else Serial.printf("%s}\n", line);
  }
  static uint32_t lastDropped = 0;
  if (dropped != lastDropped) {
    Serial.printf("{\"status\":\"dropped %lu frames\"}\n", (unsigned long)dropped);
    lastDropped = dropped;
  }
  delay(2);
}
