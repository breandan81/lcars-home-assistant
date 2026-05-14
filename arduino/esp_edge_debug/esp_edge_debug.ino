/*
 * esp_edge_debug — raw edge counter on D2
 * Flash this to the ESP to confirm signal is arriving before using HunterFan library.
 * Reports edge count + last 8 inter-edge intervals every second.
 */

static const uint8_t PIN = D2;
static const uint8_t BUF = 64;

volatile uint32_t      edgeCount = 0;
volatile uint16_t      gaps[BUF];
volatile uint8_t       head = 0;
volatile unsigned long lastEdge = 0;

void ICACHE_RAM_ATTR onEdge() {
    unsigned long now = micros();
    uint16_t gap = (uint16_t)(now - lastEdge);
    lastEdge = now;
    edgeCount++;
    gaps[head++ % BUF] = gap;
}

void setup() {
    Serial.begin(115200);
    pinMode(PIN, INPUT);
    attachInterrupt(digitalPinToInterrupt(PIN), onEdge, CHANGE);
    Serial.println(F("ESP edge debug ready. Listening on D2..."));
}

void loop() {
    delay(1000);
    noInterrupts();
    uint32_t count = edgeCount;
    uint8_t  h     = head;
    uint16_t snap[8];
    for (int i = 0; i < 8; i++)
        snap[i] = gaps[(uint8_t)(h - 8 + i) % BUF];
    interrupts();

    Serial.print(F("edges="));
    Serial.print(count);
    Serial.print(F("  last8us="));
    for (int i = 0; i < 8; i++) {
        Serial.print(snap[i]);
        if (i < 7) Serial.print(',');
    }
    Serial.println();
}
