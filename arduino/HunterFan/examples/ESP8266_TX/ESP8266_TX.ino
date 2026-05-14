/*
 * ESP8266_TX — Hunter fan transmitter test sketch
 *
 * Wiring:
 *   RF TX module DATA → D1 (GPIO5)
 *
 * Serial (115200 baud):
 *   P          → send default packet once
 *   L          → toggle continuous send loop (one per second)
 *   Any hex string terminated with newline, then bit count on next line
 *              → send custom packet  e.g.:
 *                  A6FF346CBB18067F80↵
 *                  66↵
 */

#include <HunterFan.h>

static const uint8_t TX_PIN = D1;

HunterFan fan(TX_PIN);

static const char*   DEFAULT_HEX  = "A6FF346CBB18067F80";
static const uint8_t DEFAULT_BITS = 66;

static bool   looping   = false;
static char   customHex[65];
static uint8_t customBits = 0;
static bool   awaitingBits = false;

static void doSend(const char* hex, uint8_t bits) {
    Serial.print(F("TX "));
    Serial.print(bits);
    Serial.print(F("b  "));
    Serial.println(hex);
    fan.sendHex(hex, bits);
    Serial.println(F("done"));
}

void setup() {
    Serial.begin(115200);
    fan.begin();
    Serial.println(F("ESP8266 TX ready.  P=send once  L=loop toggle"));
    Serial.println(F("Or enter hex line then bit count to send custom packet."));
}

void loop() {
    if (looping) {
        doSend(DEFAULT_HEX, DEFAULT_BITS);
        delay(1000);
    }

    if (!Serial.available()) return;
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return;

    if (line == "P") {
        doSend(DEFAULT_HEX, DEFAULT_BITS);
    } else if (line == "L") {
        looping = !looping;
        Serial.println(looping ? F("loop ON") : F("loop OFF"));
    } else if (awaitingBits) {
        customBits = (uint8_t)line.toInt();
        awaitingBits = false;
        if (customBits > 0) {
            doSend(customHex, customBits);
        } else {
            Serial.println(F("bad bit count"));
        }
    } else {
        // treat as hex string, wait for bit count next
        line.toCharArray(customHex, sizeof(customHex));
        awaitingBits = true;
        Serial.println(F("enter bit count:"));
    }
}
