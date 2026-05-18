/*
 * Garage Door Sensor — ESP8266 + HC-SR04 Ultrasonic
 * Mounts on ceiling above the door; measures distance to the door panel.
 * POSTs JSON {distance_cm, state} to LCARS server every REPORT_INTERVAL_MS.
 *
 * Door CLOSED → door panel is close to sensor (small distance)
 * Door OPEN   → sensor sees the floor or car roof (large distance)
 *
 * ── Wiring (NodeMCU / Wemos D1 Mini) ────────────────────────────────────
 *   HC-SR04  VCC  → 3.3V  (use HC-SR04P which runs at 3.3V natively)
 *                          (standard HC-SR04 needs 5V + voltage divider on ECHO)
 *   HC-SR04  GND  → GND
 *   HC-SR04  TRIG → D5 (GPIO14)
 *   HC-SR04  ECHO → D6 (GPIO12)
 *
 * !! Standard HC-SR04 ECHO outputs 5V — will damage ESP8266 !!
 *    Either use HC-SR04P (3.3V version) or add a voltage divider:
 *    ECHO pin → 1kΩ → D6, then D6 → 2kΩ → GND
 *
 * ── Libraries (install via Arduino Library Manager) ─────────────────────
 *   ESP8266WiFi       (bundled with esp8266 board package)
 *   ESP8266HTTPClient (bundled)
 *   ArduinoOTA        (bundled)
 *
 * ── Board settings ───────────────────────────────────────────────────────
 *   Board:       NodeMCU 1.0 (ESP-12E Module)  or  LOLIN(WEMOS) D1 Mini
 *   Upload speed: 115200
 *   Flash size:   4MB (FS: 2MB OTA: ~1019KB)
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoOTA.h>

// ── Configuration — edit these ────────────────────────────────────────────
const char* WIFI_SSID          = "YOUR_SSID";
const char* WIFI_PASSWORD      = "YOUR_PASSWORD";
const char* LCARS_HOST         = "192.168.68.XX";   // LCARS server IP
const int   LCARS_PORT         = 8080;
const char* OTA_HOSTNAME       = "garage-sensor";
const char* OTA_PASSWORD       = "lcars";

// Distance threshold: door is CLOSED if measured cm < this value.
// To calibrate: upload sketch, open Serial Monitor, close the door and
// note the reported distance, then set threshold to that value + 20 cm.
const float CLOSED_THRESHOLD_CM = 80.0;

// How often to send a report to the LCARS server (milliseconds)
const unsigned long REPORT_INTERVAL_MS = 5000;

// ── Pins ──────────────────────────────────────────────────────────────────
const int TRIG_PIN = 14;   // D5
const int ECHO_PIN = 12;   // D6
const int LED_PIN  = 2;    // D4 — built-in LED, active LOW

// ── Globals ───────────────────────────────────────────────────────────────
unsigned long lastReport = 0;
String        lastState  = "";

// ─────────────────────────────────────────────────────────────────────────
// Distance: average SAMPLES pings, return cm or -1 on timeout
// ─────────────────────────────────────────────────────────────────────────
float readDistanceCm() {
    const int   SAMPLES        = 5;
    const long  TIMEOUT_US     = 30000;   // ~510 cm max range
    const float SOUND_CM_PER_US = 0.01715; // 343 m/s ÷ 2 (round-trip)

    float total = 0;
    int   valid = 0;

    for (int i = 0; i < SAMPLES; i++) {
        // Trigger pulse
        digitalWrite(TRIG_PIN, LOW);
        delayMicroseconds(2);
        digitalWrite(TRIG_PIN, HIGH);
        delayMicroseconds(10);
        digitalWrite(TRIG_PIN, LOW);

        long duration = pulseIn(ECHO_PIN, HIGH, TIMEOUT_US);
        if (duration > 0) {
            total += duration * SOUND_CM_PER_US;
            valid++;
        }
        delay(30);  // let echo ring down between pings
    }

    return (valid > 0) ? (total / valid) : -1.0f;
}

// ─────────────────────────────────────────────────────────────────────────
// WiFi — connect / reconnect (non-blocking-friendly: called each loop)
// ─────────────────────────────────────────────────────────────────────────
void ensureWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;

    Serial.print("WiFi connecting");
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500);
        Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nConnected: " + WiFi.localIP().toString());
    } else {
        Serial.println("\nFailed — will retry next cycle");
    }
}

// ─────────────────────────────────────────────────────────────────────────
// POST sensor reading to LCARS
// ─────────────────────────────────────────────────────────────────────────
void reportToLcars(float distanceCm, const String& state) {
    if (WiFi.status() != WL_CONNECTED) return;

    WiFiClient client;
    HTTPClient http;

    String url = "http://" + String(LCARS_HOST) + ":" +
                 String(LCARS_PORT) + "/api/garage/sensor";
    http.begin(client, url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(4000);

    String body = "{\"distance_cm\":" + String(distanceCm, 1) +
                  ",\"state\":\"" + state + "\"}";

    int code = http.POST(body);
    if (code > 0) {
        Serial.printf("[HTTP] POST → %d\n", code);
    } else {
        Serial.printf("[HTTP] POST failed: %s\n", http.errorToString(code).c_str());
    }
    http.end();
}

// ─────────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    Serial.println("\nGarage sensor starting");

    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(LED_PIN,  OUTPUT);
    digitalWrite(LED_PIN, HIGH);  // off (active LOW)

    ensureWiFi();

    ArduinoOTA.setHostname(OTA_HOSTNAME);
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.onStart([]() {
        Serial.println("OTA: start");
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("\nOTA: done — rebooting");
    });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("OTA: %u%%\r", progress * 100 / total);
    });
    ArduinoOTA.onError([](ota_error_t err) {
        Serial.printf("OTA error[%u]\n", err);
    });
    ArduinoOTA.begin();

    Serial.printf("Ready — threshold %.0f cm, reporting every %lus\n",
                  CLOSED_THRESHOLD_CM, REPORT_INTERVAL_MS / 1000);
}

// ─────────────────────────────────────────────────────────────────────────
void loop() {
    ArduinoOTA.handle();
    ensureWiFi();

    unsigned long now = millis();
    if (now - lastReport < REPORT_INTERVAL_MS) return;
    lastReport = now;

    float dist = readDistanceCm();

    String state;
    if (dist < 0) {
        state = "UNKNOWN";
    } else if (dist < CLOSED_THRESHOLD_CM) {
        state = "CLOSED";
    } else {
        state = "OPEN";
    }

    // Blink LED to show activity
    digitalWrite(LED_PIN, LOW);
    delay(50);
    digitalWrite(LED_PIN, HIGH);

    Serial.printf("Distance: %.1f cm → %s\n", dist, state.c_str());

    reportToLcars(dist, state);
    lastState = state;
}
