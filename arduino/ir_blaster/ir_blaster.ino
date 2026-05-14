/*
 * LCARS IR Blaster — ESP8266 (NodeMCU) sketch
 *
 * Libraries (install via Arduino Library Manager):
 *   - IRremoteESP8266
 *   - ESPAsyncWebServer + ESPAsyncTCP
 *   - ArduinoJson
 *   - HunterFan  (local — symlinked from arduino/HunterFan)
 *
 * Wiring:
 *   IR LED        → D2  (GPIO4,  via 100Ω to GND)
 *   IR Recv DATA  → D5  (GPIO14, TSOP38238)
 *   Garage button → D1  (GPIO5;  idles hi-Z, pulses LOW 200ms)
 *   RF TX DATA    → D6  (GPIO12, 433 MHz transmitter module)
 *   RF RX DATA    → D7  (GPIO13, 433 MHz receiver module)
 *
 * HTTP API (port 80):
 *   GET  /ping              → { "ok": true, "ip": "..." }
 *   POST /ir/send           → { "protocol": "NEC", "code": "0x807F817E", "bits": 32 }
 *   GET  /ir/learn          → waits up to 10s for IR signal → { "code": "0x..." }
 *   POST /garage/trigger    → { "triggered": true }
 *   POST /fan/send          → { "hex": "A6FF346CBB18067F80", "bits": 66 }
 *   GET  /fan/learn         → waits for Hunter fan packet → { "hex": "...", "bits": N }
 *                             optional ?timeout=<ms>  (default 12000)
 */

#include <Arduino.h>
#if defined(ESP32)
#  include <WiFi.h>
#elif defined(ESP8266)
#  include <ESP8266WiFi.h>
#endif
#include <ESPAsyncWebServer.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>
#include <IRrecv.h>
#include <IRutils.h>
#include <ArduinoJson.h>
#include <HunterFan.h>

// ─── Config ────────────────────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";

const uint16_t IR_SEND_PIN = 4;   // D2
const uint16_t IR_RECV_PIN = 14;  // D5
const uint16_t GARAGE_PIN  = 5;   // D1; idles hi-Z, pulses LOW to trigger
const uint16_t FAN_TX_PIN  = 12;  // D6 → RF TX module DATA
const uint16_t FAN_RX_PIN  = 13;  // D7 → RF RX module DATA
const uint16_t CAPTURE_BUF = 1024;

// ─── Globals ───────────────────────────────────────────────────────────────
IRsend   irsend(IR_SEND_PIN);
IRrecv   irrecv(IR_RECV_PIN, CAPTURE_BUF, 15, true);
HunterFan fan(FAN_TX_PIN, FAN_RX_PIN);
AsyncWebServer server(80);

bool     isLearning = false;
uint32_t learnedCode = 0;
bool     learnDone   = false;
String   learnProtocol;

// ─── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  irsend.begin();
  fan.begin();
  pinMode(GARAGE_PIN, INPUT); // hi-Z until triggered

  // Connect WiFi
  Serial.printf("Connecting to %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());

  // ── Routes ────────────────────────────────────────────────────────────
  server.on("/ping", HTTP_GET, [](AsyncWebServerRequest* req) {
    String json = "{\"ok\":true,\"ip\":\"" + WiFi.localIP().toString() + "\"}";
    req->send(200, "application/json", json);
  });

  // POST /ir/send  body: { "protocol": "NEC", "code": "0x807F817E", "bits": 32 }
  server.addHandler(new AsyncCallbackJsonWebHandler("/ir/send",
    [](AsyncWebServerRequest* req, JsonVariant& body) {
      const char* proto = body["protocol"] | "NEC";
      const char* codeStr = body["code"] | "0x0";
      uint16_t    bits    = body["bits"] | 32;

      uint32_t code = (uint32_t)strtoul(codeStr, nullptr, 16);
      bool ok = sendCode(proto, code, bits);

      StaticJsonDocument<128> resp;
      resp["sent"]     = ok;
      resp["protocol"] = proto;
      resp["code"]     = codeStr;
      resp["bits"]     = bits;
      String out; serializeJson(resp, out);
      req->send(200, "application/json", out);
    }
  ));

  // GET /ir/learn — waits up to 10s for a code
  server.on("/ir/learn", HTTP_GET, [](AsyncWebServerRequest* req) {
    isLearning  = true;
    learnDone   = false;
    learnedCode = 0;
    learnProtocol = "";

    irrecv.enableIRIn();
    unsigned long deadline = millis() + 10000;
    decode_results results;

    while (millis() < deadline) {
      if (irrecv.decode(&results)) {
        learnedCode = results.value;
        learnProtocol = typeToString(results.decode_type, false);
        learnDone = true;
        irrecv.resume();
        irrecv.disableIRIn();
        break;
      }
      delay(50);
    }

    isLearning = false;
    StaticJsonDocument<256> resp;
    if (learnDone) {
      char hexbuf[12];
      snprintf(hexbuf, sizeof(hexbuf), "0x%08X", learnedCode);
      resp["code"]     = hexbuf;
      resp["protocol"] = learnProtocol;
      resp["raw_value"]= learnedCode;
    } else {
      resp["error"] = "timeout — no IR signal received";
    }
    String out; serializeJson(resp, out);
    req->send(200, "application/json", out);
  });

  // POST /garage/trigger — pulse button pin LOW for 200ms
  server.on("/garage/trigger", HTTP_POST, [](AsyncWebServerRequest* req) {
    pinMode(GARAGE_PIN, OUTPUT);
    digitalWrite(GARAGE_PIN, LOW);
    delay(200);
    pinMode(GARAGE_PIN, INPUT); // back to hi-Z
    req->send(200, "application/json", "{\"triggered\":true}");
  });

  // POST /fan/send  { "hex": "A6FF346CBB18067F80", "bits": 66 }
  server.addHandler(new AsyncCallbackJsonWebHandler("/fan/send",
    [](AsyncWebServerRequest* req, JsonVariant& body) {
      const char* hex = body["hex"] | "";
      uint8_t bits    = body["bits"] | 66;
      fan.sendHex(hex, bits);
      req->send(200, "application/json", "{\"sent\":true}");
    }
  ));

  // GET /fan/learn?timeout=12000
  server.on("/fan/learn", HTTP_GET, [](AsyncWebServerRequest* req) {
    uint32_t ms = 12000;
    if (req->hasParam("timeout"))
      ms = (uint32_t)req->getParam("timeout")->value().toInt();

    uint8_t data[16];
    uint8_t bits = 0;
    if (fan.receive(data, sizeof(data), bits, ms)) {
      const char* hex = HunterFan::toHex(data, (bits + 7) / 8);
      String json = String("{\"hex\":\"") + hex + "\",\"bits\":" + bits + "}";
      req->send(200, "application/json", json);
    } else {
      req->send(200, "application/json",
        "{\"error\":\"timeout — no Hunter fan signal received\"}");
    }
  });

  // CORS for local dev
  DefaultHeaders::Instance().addHeader("Access-Control-Allow-Origin", "*");

  server.begin();
  Serial.println("HTTP server started");
}

// ─── Loop ──────────────────────────────────────────────────────────────────
void loop() {
  // Nothing needed — AsyncWebServer handles everything in callbacks.
  // Watchdog and WiFi reconnect:
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi lost, reconnecting…");
    WiFi.reconnect();
    delay(5000);
  }
  delay(100);
}

// ─── sendCode: dispatch to IRsend by protocol name ─────────────────────────
bool sendCode(const char* protocol, uint32_t code, uint16_t bits) {
  String p = String(protocol);
  p.toUpperCase();

  if (p == "NEC" || p == "NEC2") {
    irsend.sendNEC(code, bits);
  } else if (p == "SAMSUNG") {
    irsend.sendSAMSUNG(code, bits);
  } else if (p == "SONY") {
    irsend.sendSony(code, bits, 2); // Sony needs 2–3 repeats
  } else if (p == "RC5") {
    irsend.sendRC5(code, bits);
  } else if (p == "RC6") {
    irsend.sendRC6(code, bits);
  } else if (p == "LG") {
    irsend.sendLG(code, bits);
  } else if (p == "PANASONIC") {
    irsend.sendPanasonic(code >> 16, code & 0xFFFF);
  } else if (p == "SHARP") {
    irsend.sendSharpRaw(code, bits);
  } else if (p == "PIONEER") {
    irsend.sendPioneer(code, bits);
  } else {
    // Fallback: send as raw NEC
    irsend.sendNEC(code, bits);
    return false;
  }
  return true;
}
