#include "settings.h"

#include <Preferences.h>
#include <Wire.h>

#include "config.h"
#include "ppg.h"

Settings cfg;
bool rawMode = false;
static bool touched = false;
static String line;

static const char* HELP =
    "commands (settings are saved; type reboot to apply):\n"
    "  show                     current settings and sensors\n"
    "  id C002                  animal id\n"
    "  ssid My Hotspot          Wi-Fi name (spaces allowed)\n"
    "  pass secret123           Wi-Fi password\n"
    "  mqtt 192.168.1.20 [1883] laptop/Pi running Mosquitto\n"
    "  user lms | mqttpass xyz  MQTT login (same as MQTT_* in the repo .env)\n"
    "  ppg auto|max30102|max30100|dfrobot|analog|none\n"
    "  battery on|off           battery divider wired to the battery pin?\n"
    "  scan                     list I2C devices (wiring check)\n"
    "  raw                      stream raw pulse + acceleration (again to stop)\n"
    "  factory                  forget saved settings\n"
    "  reboot";

void settingsLoad() {
  Preferences p;
  p.begin("lms", false);
  cfg.id = p.getString("id", ANIMAL_ID);
  cfg.ssid = p.getString("ssid", WIFI_SSID);
  cfg.pass = p.getString("pass", WIFI_PASSWORD);
  cfg.mqttHost = p.getString("mhost", MQTT_HOST);
  cfg.mqttPort = p.getUShort("mport", MQTT_PORT);
  cfg.mqttUser = p.getString("muser", MQTT_USER);
  cfg.mqttPass = p.getString("mpass", MQTT_PASSWORD);
  cfg.ppg = p.getChar("ppg", PPG_DEFAULT);
  cfg.battery = p.getBool("bat", HAVE_BATTERY);
  p.end();
}

static void saveStr(const char* key, const String& v) {
  Preferences p;
  p.begin("lms", false);
  p.putString(key, v);
  p.end();
}

static void saved(const char* what, const String& v) {
  Serial.printf("ok: %s = %s (saved; type reboot to apply)\n", what, v.c_str());
}

void i2cScan() {
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() != 0) continue;
    found++;
    Serial.printf("  0x%02X  ", a);
    if (a == 0x57) {
      uint8_t id = ppgPartId();
      if (id == 0x15) Serial.println("MAX30102/MAX30105 pulse sensor");
      else if (id == 0x11) Serial.println("MAX30100 pulse sensor");
      else Serial.printf("pulse module (part id 0x%02X) - probably DFRobot SEN0344\n", id);
    } else if (a == 0x68 || a == 0x69) {
      Serial.println("MPU6050-family accelerometer");
    } else if (a == 0x3C || a == 0x3D) {
      Serial.println("OLED display");
    } else if (a == 0x76 || a == 0x77) {
      Serial.println("BMP/BME280");
    } else {
      Serial.println("unknown");
    }
  }
  if (!found) Serial.printf("  nothing on I2C: check SDA=%d SCL=%d, 3.3V and GND\n", PIN_SDA, PIN_SCL);
}

static void run(String cmd) {
  cmd.trim();
  if (cmd.isEmpty()) return;
  touched = true;
  int sp = cmd.indexOf(' ');
  String name = sp < 0 ? cmd : cmd.substring(0, sp);
  String arg = sp < 0 ? "" : cmd.substring(sp + 1);
  arg.trim();
  name.toLowerCase();

  if (name == "help" || name == "?") {
    Serial.println(HELP);
  } else if (name == "show") {
    Serial.printf("id=%s ssid=\"%s\" pass=%s mqtt=%s:%u user=%s ppg=%s battery=%s\n", cfg.id.c_str(),
                  cfg.ssid.c_str(), cfg.pass.isEmpty() ? "(none)" : "****", cfg.mqttHost.c_str(), cfg.mqttPort,
                  cfg.mqttUser.c_str(), ppgName(cfg.ppg), cfg.battery ? "on" : "off");
    printStatus();
  } else if (name == "id" && arg.length()) {
    saveStr("id", arg);
    saved("id", arg);
  } else if (name == "ssid") {
    saveStr("ssid", arg);
    saved("ssid", arg);
  } else if (name == "pass") {
    saveStr("pass", arg);
    saved("pass", arg.isEmpty() ? "(none)" : "****");
  } else if (name == "mqtt" && arg.length()) {
    int sp2 = arg.indexOf(' ');
    String host = sp2 < 0 ? arg : arg.substring(0, sp2);
    uint16_t port = sp2 < 0 ? MQTT_PORT : arg.substring(sp2 + 1).toInt();
    Preferences p;
    p.begin("lms", false);
    p.putString("mhost", host);
    p.putUShort("mport", port ? port : MQTT_PORT);
    p.end();
    saved("mqtt", host + ":" + String(port ? port : MQTT_PORT));
  } else if (name == "user" && arg.length()) {
    saveStr("muser", arg);
    saved("mqtt user", arg);
  } else if (name == "mqttpass") {
    saveStr("mpass", arg);
    saved("mqtt password", "****");
  } else if (name == "ppg" && ppgFromName(arg) != -2) {
    Preferences p;
    p.begin("lms", false);
    p.putChar("ppg", ppgFromName(arg));
    p.end();
    saved("ppg", arg);
  } else if (name == "battery" && (arg == "on" || arg == "off")) {
    Preferences p;
    p.begin("lms", false);
    p.putBool("bat", arg == "on");
    p.end();
    saved("battery", arg);
  } else if (name == "scan") {
    i2cScan();
  } else if (name == "raw") {
    rawMode = !rawMode;
    Serial.println(rawMode ? "raw on (type raw to stop)" : "raw off");
  } else if (name == "factory") {
    Preferences p;
    p.begin("lms", false);
    p.clear();
    p.end();
    Serial.println("ok: saved settings cleared, defaults from lms_config after reboot");
  } else if (name == "reboot") {
    Serial.println("rebooting");
    Serial.flush();
    ESP.restart();
  } else {
    Serial.printf("unknown or incomplete command: %s (type help)\n", cmd.c_str());
  }
}

void settingsPoll() {
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

bool settingsTouched() { return touched; }
