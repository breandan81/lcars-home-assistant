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
#  include <ESPmDNS.h>
#elif defined(ESP8266)
#  include <ESP8266WiFi.h>
#  include <ESP8266mDNS.h>
#endif
#include <ArduinoJson.h>          // must precede ESPAsyncWebServer.h so ASYNC_JSON_SUPPORT enables
#include <ESPAsyncWebServer.h>
#include <AsyncJson.h>
#include <IRremoteESP8266.h>
#include <IRsend.h>
#include <IRrecv.h>
#include <IRutils.h>
#include <HunterFan.h>
#include "wifi_credentials.h"  // gitignored; copy wifi_credentials.example.h

// ─── Config ────────────────────────────────────────────────────────────────

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

// Deferred IR send queue: HTTP handler enqueues, main loop transmits.
// Async callbacks run on a small stack & timing-sensitive IRsend calls
// can crash the ESP if invoked there directly.
volatile bool     pendingIR = false;
String            pendingProto;
uint32_t          pendingCode = 0;
uint16_t          pendingBits = 32;

// ─── Setup ─────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  irsend.begin();
  fan.begin();
  pinMode(GARAGE_PIN, INPUT); // hi-Z until triggered

  // Connect WiFi
  WiFi.mode(WIFI_STA);
  WiFi.hostname(DEVICE_NAME);
  Serial.printf("Connecting to %s as %s", WIFI_SSID, DEVICE_NAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());

  // mDNS — advertise as <DEVICE_NAME>.local so LCARS can find us by name
  if (MDNS.begin(DEVICE_NAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("mDNS: http://%s.local\n", DEVICE_NAME);
  } else {
    Serial.println("mDNS start failed");
  }

  // ── Routes ────────────────────────────────────────────────────────────
  server.on("/ping", HTTP_GET, [](AsyncWebServerRequest* req) {
    String json = "{\"ok\":true,\"ip\":\"" + WiFi.localIP().toString() + "\"}";
    req->send(200, "application/json", json);
  });

  // POST /ir/send?protocol=NEC&code=0x807F817E&bits=32
  // Defers the actual IR transmit to the main loop — calling irsend.sendNEC()
  // directly from the async callback crashed the ESP (Exception 9, excvaddr=3).
  server.on("/ir/send", HTTP_POST, [](AsyncWebServerRequest* req) {
    String proto   = req->hasParam("protocol") ? req->getParam("protocol")->value() : "NEC";
    String codeStr = req->hasParam("code")     ? req->getParam("code")->value()     : "0x0";
    uint16_t bits  = req->hasParam("bits")     ? (uint16_t)req->getParam("bits")->value().toInt() : 32;

    pendingProto = proto;
    pendingCode  = (uint32_t)strtoul(codeStr.c_str(), nullptr, 16);
    pendingBits  = bits;
    pendingIR    = true;

    String resp = String("{\"queued\":true,\"protocol\":\"") + proto +
                  "\",\"code\":\"" + codeStr + "\",\"bits\":" + bits + "}";
    req->send(200, "application/json", resp);
  });

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

  // POST /fan/send?hex=A6FF...&bits=66
  server.on("/fan/send", HTTP_POST, [](AsyncWebServerRequest* req) {
    String hex = req->hasParam("hex") ? req->getParam("hex")->value() : "";
    uint8_t bits = req->hasParam("bits") ? (uint8_t)req->getParam("bits")->value().toInt() : 66;
    fan.sendHex(hex.c_str(), bits);
    req->send(200, "application/json", "{\"sent\":true}");
  });

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
#if defined(ESP8266)
  MDNS.update();   // ESP8266 mDNS needs periodic servicing; ESP32 doesn't
#endif

  // Drain deferred IR send queue (set by HTTP callbacks).
  if (pendingIR) {
    pendingIR = false;
    sendCode(pendingProto.c_str(), pendingCode, pendingBits);
    Serial.printf("IR sent: %s 0x%08X (%d bits)\n",
                  pendingProto.c_str(), pendingCode, pendingBits);
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi lost, reconnecting…");
    WiFi.reconnect();
    delay(5000);
  }
  delay(10);
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
