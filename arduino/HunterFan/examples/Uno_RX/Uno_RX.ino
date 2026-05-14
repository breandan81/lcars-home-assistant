/*
 * Uno_RX — Hunter fan receiver test sketch
 *
 * Wiring:
 *   RF RX module DATA → Pin 2  (must be INT0)
 *
 * Serial (115200 baud):
 *   Prints each decoded packet as:
 *     #N  RX <bits>b  <hex>
 *
 * Compare the printed hex against what the TX side sent to verify correctness.
 */

#include <HunterFan.h>

static const uint8_t RX_PIN = 2;

HunterFan fan(0xFF, RX_PIN);

static uint32_t rxCount = 0;

void setup() {
    Serial.begin(115200);
    fan.begin();
    Serial.println(F("Uno RX ready. Listening..."));
}

void loop() {
    uint8_t data[16];
    uint8_t bits = 0;

    if (fan.receive(data, sizeof(data), bits, 2000)) {
        rxCount++;
        Serial.print(F("#"));
        Serial.print(rxCount);
        Serial.print(F("  RX "));
        Serial.print(bits);
        Serial.print(F("b  "));
        Serial.println(HunterFan::toHex(data, (bits + 7) / 8));
    }
}
