/*
 * HunterFanBasic — send/receive example for ESP8266 and Uno
 *
 * Wiring (ESP8266 NodeMCU):
 *   RF TX module DATA → D1 (GPIO5)
 *   RF RX module DATA → D2 (GPIO4)
 *
 * Wiring (Arduino Uno):
 *   RF TX module DATA → Pin 10
 *   RF RX module DATA → Pin 2  (must be an interrupt pin)
 *
 * Serial commands (115200 baud):
 *   P  — send the hardcoded command
 *   R  — receive and print one packet
 */

#include <HunterFan.h>

#if defined(ESP8266)
  static const uint8_t TX_PIN = D1;
  static const uint8_t RX_PIN = D2;
#else
  static const uint8_t TX_PIN = 10;
  static const uint8_t RX_PIN = 2;
#endif

HunterFan fan(TX_PIN, RX_PIN);

// Captured from a real Hunter remote — replace with your own
static const char*    CMD_HEX  = "A6FF346CBB18067F80";
static const uint8_t  CMD_BITS = 66;

void setup() {
    Serial.begin(115200);
    fan.begin();
    Serial.println(F("HunterFan ready.  P = send  R = receive"));
}

void loop() {
    if (!Serial.available()) return;
    char cmd = Serial.read();

    if (cmd == 'P') {
        Serial.println(F("Sending..."));
        fan.sendHex(CMD_HEX, CMD_BITS);
        Serial.println(F("Done."));

    } else if (cmd == 'R') {
        Serial.println(F("Waiting for packet..."));
        uint8_t data[16];
        uint8_t bits = 0;
        if (fan.receive(data, sizeof(data), bits)) {
            Serial.print(F("Received "));
            Serial.print(bits);
            Serial.print(F("b: "));
            Serial.println(HunterFan::toHex(data, (bits + 7) / 8));
        } else {
            Serial.println(F("Timeout / decode error"));
        }
    }
}
