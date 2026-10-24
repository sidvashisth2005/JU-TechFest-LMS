// LMS cattle collar firmware for ESP8266 (ESPresso Lite V2 / ESP-WROOM-02, NodeMCU).
//
// Every REPORT_SECONDS one JSON reading matching common/schemas.py VitalsMsg goes to
// lms/collar/<id>/vitals:
//   {"animal_id":"C001","hr":null,"spo2":null,"body_temp":null,"activity":0.041,"steps":3,"battery":null,"rssi":-61}
// Every ENV_SECONDS the DHT22 air reading goes to lms/barn/<id>-collar/env as an EnvMsg, so the
// dashboard's Environment page shows the air right at the animal (heat stress / THI).
// A sensor that is missing or has no valid reading sends null - never a made-up value.
// No pulse sensor yet (hr/spo2 null); no timestamp (no clock - the backend stamps receive time).
//
// Every reading is also printed as a JSON line on USB serial, so the collar works on a cable
// without Wi-Fi: `python -m barn.serial_bridge --port COM12` forwards the lines to MQTT.
//
// Sensors: GY-521 (any MPU6050-family chip, via LmsImu) and the SSD1306 OLED share I2C;
// DHT22 on its own pin. Everything is optional and detected at boot (`scan` lists I2C).
// The GPIO13 button turns the OLED off/on (saves ~20 mA).

#include <Arduino.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <ESP8266WiFi.h>
#include <LittleFS.h>
#include <LmsImu.h>
#include <PubSubClient.h>
#include <SSD1306Wire.h>
#include <Wire.h>

#if __has_include("lms_config.h")
#include "lms_config.h"
#else
#include "lms_config.example.h"
#warning "Using lms_config.example.h defaults - set Wi-Fi/MQTT over serial (type help) or create lms_config.h"
#endif

// ---------------------------------------------------------------- settings (LittleFS)
struct Settings {
  String id, ssid, pass, mqttHost, mqttUser, mqttPass;
  uint16_t mqttPort;
} cfg;

static const char* CFG_FILE = "/lms.cfg";
static const char* HELP =
    "commands (settings are saved; type reboot to apply):\n"
    "  show                     current settings and sensors\n"
    "  id C002                  animal id\n"
    "  ssid My Hotspot          Wi-Fi name (spaces allowed, 2.4 GHz only)\n"
    "  pass secret123           Wi-Fi password\n"
    "  mqtt 192.168.1.20 [1883] laptop/Pi running Mosquitto\n"
    "  user lms | mqttpass xyz  MQTT login (same as MQTT_* in the repo .env)\n"
    "  scan                     list I2C devices (wiring check)\n"
    "  scanall                  try every SDA/SCL pin pair (find which pins a device is on)\n"
    "  lines                    is a powered I2C module really wired to SDA and SCL?\n"
    "  msg Hello | fill         big text / all-white OLED for 10 s (display test)\n"
    "  raw                      stream acceleration + DHT22 (again to stop)\n"
    "  factory                  forget saved settings\n"
    "  reboot";

void settingsLoad() {
  cfg = {ANIMAL_ID, WIFI_SSID, WIFI_PASSWORD, MQTT_HOST, MQTT_USER, MQTT_PASSWORD, MQTT_PORT};
  File f = LittleFS.open(CFG_FILE, "r");
  if (!f) return;
  while (f.available()) {
    String line = f.readStringUntil('\n');
    int eq = line.indexOf('=');
    if (eq < 1) continue;
    String k = line.substring(0, eq), v = line.substring(eq + 1);
    if (k == "id") cfg.id = v;
    else if (k == "ssid") cfg.ssid = v;
    else if (k == "pass") cfg.pass = v;
    else if (k == "mhost") cfg.mqttHost = v;
    else if (k == "mport") cfg.mqttPort = v.toInt();
    else if (k == "muser") cfg.mqttUser = v;
    else if (k == "mpass") cfg.mqttPass = v;
  }
  f.close();
}

bool settingsSave() {
  File f = LittleFS.open(CFG_FILE, "w");
  if (!f) return false;
  f.printf("id=%s\nssid=%s\npass=%s\nmhost=%s\nmport=%u\nmuser=%s\nmpass=%s\n", cfg.id.c_str(), cfg.ssid.c_str(),
           cfg.pass.c_str(), cfg.mqttHost.c_str(), cfg.mqttPort, cfg.mqttUser.c_str(), cfg.mqttPass.c_str());
  f.close();
  return true;
}

// ---------------------------------------------------------------- sensors
LmsImu imu;
LmsActivity act;
DHT dht(PIN_DHT, DHT22);
SSD1306Wire* oled = nullptr;
bool haveImu = false, haveOled = false, oledOn = true, rawMode = false;
float lastG = 0, airT = NAN, airH = NAN;
uint32_t lastImu = 0, lastRaw = 0, lastDht = 0, lastDhtOk = 0, lastReport = 0, lastEnv = 0, lastOled = 0, sent = 0;

bool i2cPresent(uint8_t a) {
  Wire.beginTransmission(a);
  return Wire.endTransmission() == 0;
}

void i2cScan() {
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    if (!i2cPresent(a)) continue;
    found++;
    Serial.printf("  0x%02X  %s\n", a,
                  a == 0x68 || a == 0x69   ? "MPU6050-family accelerometer (GY-521)"
                  : a == 0x3C || a == 0x3D ? "OLED display"
                  : a == 0x57              ? "pulse sensor (MAX3010x / DFRobot)"
                                           : "unknown");
  }
  if (!found) Serial.printf("  nothing on I2C: check SDA=%d SCL=%d, 3.3V and GND (try scanall)\n", PIN_SDA, PIN_SCL);
}

// `scanall`: try every SDA/SCL pin pair, for boards whose I2C pins are not the usual 4/5.
// Restores the configured pins afterwards.
void i2cScanAll() {
  // not 0/2/15 (boot-mode pins: driving them hung the scan) nor 1/3 (USB serial)
  const uint8_t pins[] = {4, 5, 12, 13, 14};
  int hits = 0;
  Serial.println("  scanning pin pairs...");
  for (uint8_t sda : pins) {
    for (uint8_t scl : pins) {
      if (sda == scl) continue;
      Wire.begin(sda, scl);
      Wire.setClockStretchLimit(2000);  // a wrong pair must not stall the bus
      for (uint8_t a = 8; a < 120; a++) {
        yield();  // keep the watchdog fed
        if (!i2cPresent(a)) continue;
        Serial.printf("  SDA=%u SCL=%u -> 0x%02X\n", sda, scl, a);
        hits++;
      }
    }
  }
  Wire.begin(PIN_SDA, PIN_SCL);
  if (!hits) Serial.println("  no I2C device on any pin pair: check the device's power (3V3/GND)");
}

// `lines`: is anything with pull-ups (every I2C module has them) really on SDA/SCL? Pull the pin
// low, let go, and read it back: a connected, powered module pulls it HIGH within microseconds;
// a broken wire or unpowered module leaves it LOW. Tells which of the two wires is the problem.
void i2cLineTest() {
  const uint8_t pins[2] = {PIN_SDA, PIN_SCL};
  const char* names[2] = {"SDA", "SCL"};
  for (uint8_t i = 0; i < 2; i++) {
    pinMode(pins[i], OUTPUT);
    digitalWrite(pins[i], LOW);
    delayMicroseconds(100);
    pinMode(pins[i], INPUT);  // no internal pull-up: only the module's resistors can raise it
    delayMicroseconds(30);
    bool high = digitalRead(pins[i]);
    Serial.printf("  %s (GPIO%u): %s\n", names[i], pins[i],
                  high ? "HIGH - module connected and powered" : "LOW - wire not reaching / module unpowered");
  }
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000);
}

void setupSensors() {
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000);  // 100 kHz: long jumper wires + several devices; faster gave ghost addresses
  haveImu = imu.begin(Wire);
  uint8_t oledAddr = i2cPresent(0x3C) ? 0x3C : i2cPresent(0x3D) ? 0x3D : 0;
  if (oledAddr) {
    // the library defaults to 700 kHz, too fast for jumper wires shared with the IMU/PPG
    oled = new SSD1306Wire(oledAddr, PIN_SDA, PIN_SCL, GEOMETRY_128_64, I2C_ONE, 100000);
    haveOled = oled->init();
    if (haveOled) oled->flipScreenVertically();
  }
  dht.begin();
  Serial.printf("collar %s  imu:%s", cfg.id.c_str(), haveImu ? "yes" : "no");
  if (haveImu) Serial.printf(" (0x%02X id 0x%02X)", imu.addr, imu.whoami);
  Serial.printf("  oled:%s  dht22: first read in 2 s\n", haveOled ? "yes" : "no");
}

void sampleSensors() {
  uint32_t now = millis();
  if (haveImu && now - lastImu >= 20) {  // 50 Hz
    lastImu = now;
    if (imu.readG(lastG)) act.add(lastG, now);
  }
  if (now - lastDht >= 2500) {  // DHT22 needs >= 2 s between reads
    lastDht = now;
    float t = dht.readTemperature(), h = dht.readHumidity();
    if (!isnan(t) && !isnan(h)) {
      airT = t;
      airH = h;
      lastDhtOk = now;
    }
  }
  if (lastDhtOk && now - lastDhtOk > 15000) airT = airH = NAN;  // stale = unplugged
  if (rawMode && now - lastRaw >= 100) {
    lastRaw = now;
    Serial.printf("g:%.3f air_t:%.1f air_h:%.1f\n", lastG, airT, airH);
  }
}

// ---------------------------------------------------------------- Wi-Fi + MQTT
WiFiClient net;
PubSubClient mqtt(net);
String topicVitals, topicEnv;
uint32_t lastWifiTry = 0, lastMqttTry = 0;
bool wifiStarted = false, wifiAnnounced = false;

void startWifi() {
  if (cfg.ssid.isEmpty()) return;
  WiFi.mode(WIFI_STA);
  WiFi.hostname("lms-collar-" + cfg.id);  // shown in the hotspot's device list instead of the MAC
  WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
  wifiStarted = true;
  lastWifiTry = millis();
  Serial.printf("wifi: connecting to \"%s\"\n", cfg.ssid.c_str());
}

void maintainNet() {
  if (cfg.ssid.isEmpty()) return;
  if (WiFi.status() != WL_CONNECTED) {
    wifiAnnounced = false;
    static uint32_t lastWhy = 0;
    if (wifiStarted && millis() - lastWhy > 5000) {  // say why, so a failed join is obvious
      lastWhy = millis();
      wl_status_t st = WiFi.status();
      Serial.printf("wifi: not connected (%d %s)\n", st,
                    st == WL_NO_SSID_AVAIL     ? "network not found - 2.4 GHz? name right?"
                    : st == WL_WRONG_PASSWORD  ? "wrong password"
                    : st == WL_CONNECT_FAILED  ? "connect failed - hotspot full or rejected"
                    : st == WL_DISCONNECTED    ? "still trying"
                    : st == WL_CONNECTION_LOST ? "connection lost"
                                               : "idle");
    }
    if (!wifiStarted || millis() - lastWifiTry > 20000) startWifi();
    return;
  }
  if (!wifiAnnounced) {
    wifiAnnounced = true;
    Serial.printf("wifi: connected, ip %s, rssi %d dBm\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  }
  if (!mqtt.connected() && millis() - lastMqttTry > 5000) {
    lastMqttTry = millis();
    String cid = "lms-collar-" + cfg.id;
    bool ok = mqtt.connect(cid.c_str(), cfg.mqttUser.c_str(), cfg.mqttPass.c_str());
    Serial.printf("mqtt %s:%u %s", cfg.mqttHost.c_str(), cfg.mqttPort, ok ? "connected\n" : "failed");
    if (!ok) Serial.printf(" rc=%d (4/5 = wrong user/password, -2 = host unreachable or port 1883 blocked)\n",
                           mqtt.state());
  }
  mqtt.loop();
}

void publish(const String& topic, JsonDocument& doc) {
  char payload[256];
  size_t n = serializeJson(doc, payload, sizeof(payload));
  Serial.println(payload);  // USB serial copy (backup path via barn/serial_bridge.py)
  if (mqtt.connected()) mqtt.publish(topic.c_str(), (const uint8_t*)payload, n, false);
}

void sendVitals() {
  JsonDocument doc;
  doc["animal_id"] = cfg.id;
  doc["hr"] = nullptr;  // no pulse sensor on this collar yet
  doc["spo2"] = nullptr;
  doc["body_temp"] = nullptr;
  if (act.n) doc["activity"] = roundf(act.mean() * 10000) / 10000;
  else doc["activity"] = nullptr;
  if (haveImu) doc["steps"] = act.steps;
  else doc["steps"] = nullptr;
  doc["battery"] = nullptr;  // no battery divider wired
  if (WiFi.status() == WL_CONNECTED) doc["rssi"] = WiFi.RSSI();
  act.reset();
  publish(topicVitals, doc);
  sent++;
  digitalWrite(PIN_LED, LOW);  // short blink
  delay(20);
  digitalWrite(PIN_LED, HIGH);
}

void sendEnv() {
  if (isnan(airT)) return;  // nothing valid to report
  JsonDocument doc;
  doc["station_id"] = cfg.id + "-collar";
  doc["temp"] = roundf(airT * 10) / 10;
  doc["humidity"] = roundf(airH * 10) / 10;
  doc["pressure"] = nullptr;
  publish(topicEnv, doc);
}

// ---------------------------------------------------------------- OLED
// `msg <text>` / `fill`: a big message or an all-white screen for 10 s, to test the display.
String oledMsg;
bool oledFill = false;
uint32_t oledMsgUntil = 0;

void drawOled() {
  if (!haveOled || millis() - lastOled < 500) return;
  lastOled = millis();
  if (!oledOn) return;
  if (millis() < oledMsgUntil) {
    oled->clear();
    if (oledFill) {
      oled->fillRect(0, 0, 128, 64);
    } else {
      oled->setFont(ArialMT_Plain_24);
      oled->setTextAlignment(TEXT_ALIGN_CENTER);
      oled->drawStringMaxWidth(64, 8, 128, oledMsg);
      oled->setTextAlignment(TEXT_ALIGN_LEFT);
    }
    oled->display();
    return;
  }
  bool wifi = WiFi.status() == WL_CONNECTED;
  oled->clear();
  oled->setFont(ArialMT_Plain_10);
  oled->drawString(0, 0, cfg.id + "  wifi:" + (wifi ? "ok" : "--") + " mqtt:" + (mqtt.connected() ? "ok" : "--"));
  oled->drawString(0, 13, haveImu ? "move " + String(fabs(lastG - 1.0f), 2) + " g  steps " + String(act.steps)
                                  : "accelerometer: none");
  oled->drawString(0, 26, isnan(airT) ? "air: no DHT22" : "air " + String(airT, 1) + " C  " + String(airH, 0) + " %");
  oled->drawString(0, 39, wifi ? WiFi.localIP().toString() : cfg.ssid.isEmpty() ? "no wifi set" : "joining " + cfg.ssid);
  oled->drawString(0, 52, "sent " + String(sent));
  oled->display();
}

void pollButton() {
  static bool was = HIGH;
  static uint32_t t = 0;
  bool now = digitalRead(PIN_BUTTON);
  if (was == HIGH && now == LOW && millis() - t > 250) {
    t = millis();
    oledOn = !oledOn;
    if (haveOled) oledOn ? oled->displayOn() : oled->displayOff();
  }
  was = now;
}

// ---------------------------------------------------------------- serial commands
String line;

void printStatus() {
  Serial.printf("id=%s ssid=\"%s\" pass=%s mqtt=%s:%u user=%s\n", cfg.id.c_str(), cfg.ssid.c_str(),
                cfg.pass.isEmpty() ? "(none)" : "****", cfg.mqttHost.c_str(), cfg.mqttPort, cfg.mqttUser.c_str());
  Serial.printf("imu=%s oled=%s dht22=%s wifi=%s mqtt=%s\n", haveImu ? "yes" : "no", haveOled ? "yes" : "no",
                isnan(airT) ? "no reading" : "ok", WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "down",
                mqtt.connected() ? "up" : "down");
}

void run(String cmd) {
  cmd.trim();
  if (cmd.isEmpty()) return;
  int sp = cmd.indexOf(' ');
  String name = sp < 0 ? cmd : cmd.substring(0, sp);
  String arg = sp < 0 ? "" : cmd.substring(sp + 1);
  arg.trim();
  name.toLowerCase();
  bool changed = true;

  if (name == "help" || name == "?") {
    Serial.println(HELP);
    changed = false;
  } else if (name == "show") {
    printStatus();
    changed = false;
  } else if (name == "id" && arg.length()) {
    cfg.id = arg;
  } else if (name == "ssid") {
    cfg.ssid = arg;
  } else if (name == "pass") {
    cfg.pass = arg;
  } else if (name == "mqtt" && arg.length()) {
    int sp2 = arg.indexOf(' ');
    cfg.mqttHost = sp2 < 0 ? arg : arg.substring(0, sp2);
    uint16_t port = sp2 < 0 ? MQTT_PORT : arg.substring(sp2 + 1).toInt();
    cfg.mqttPort = port ? port : MQTT_PORT;
  } else if (name == "user" && arg.length()) {
    cfg.mqttUser = arg;
  } else if (name == "mqttpass") {
    cfg.mqttPass = arg;
  } else if (name == "scan") {
    i2cScan();
    changed = false;
  } else if (name == "scanall") {
    i2cScanAll();
    changed = false;
  } else if (name == "lines") {
    i2cLineTest();
    changed = false;
  } else if (name == "msg" || name == "fill") {
    oledMsg = arg;
    oledFill = name == "fill";
    oledMsgUntil = millis() + 10000;
    lastOled = 0;
    Serial.println(haveOled ? "ok: on the OLED for 10 s" : "no OLED found at boot (scan, then reboot)");
    changed = false;
  } else if (name == "raw") {
    rawMode = !rawMode;
    Serial.println(rawMode ? "raw on (type raw to stop)" : "raw off");
    changed = false;
  } else if (name == "factory") {
    LittleFS.remove(CFG_FILE);
    Serial.println("ok: saved settings cleared, defaults from lms_config after reboot");
    changed = false;
  } else if (name == "reboot") {
    Serial.println("rebooting");
    Serial.flush();
    ESP.restart();
  } else {
    Serial.printf("unknown or incomplete command: %s (type help)\n", cmd.c_str());
    changed = false;
  }
  if (changed) Serial.println(settingsSave() ? "ok: saved; type reboot to apply" : "error: could not save");
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (line.length()) run(line);
      line = "";
    } else if (line.length() < 120) {
      line += c;
    }
  }
}

// ----------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  if (!LittleFS.begin()) Serial.println("LittleFS mount failed - settings won't be saved");
  settingsLoad();
  setupSensors();
  topicVitals = "lms/collar/" + cfg.id + "/vitals";
  topicEnv = "lms/barn/" + cfg.id + "-collar/env";
  mqtt.setServer(cfg.mqttHost.c_str(), cfg.mqttPort);
  if (cfg.ssid.isEmpty()) Serial.println("no Wi-Fi set: readings go to USB serial only (type help)");
  else startWifi();
  lastReport = lastEnv = millis();
  Serial.println("ready (type help for commands)");
}

void loop() {
  pollSerial();
  sampleSensors();
  maintainNet();
  pollButton();
  drawOled();
  if (millis() - lastReport >= REPORT_SECONDS * 1000UL) {
    lastReport = millis();
    sendVitals();
  }
  if (millis() - lastEnv >= ENV_SECONDS * 1000UL) {
    lastEnv = millis();
    sendEnv();
  }
  delay(2);
}
