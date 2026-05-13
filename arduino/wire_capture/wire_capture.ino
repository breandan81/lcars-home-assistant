/*
 * wire_capture — captures raw edge-to-edge periods into RAM, dumps after gap.
 * Pin 2 (INT0), 115200 baud.
 * Stores uint16_t deltas so 256 samples fits in ~512 bytes of RAM.
 * One Hunter frame: ~120 preamble + 2 anchor + 132 data edges = 254 periods.
 */

#define RX_PIN      2
#define MAX_PERIODS 256

volatile uint16_t      periods[MAX_PERIODS];
volatile uint16_t      count    = 0;
volatile unsigned long lastEdge = 0;
volatile bool          bufFull  = false;

void onEdge() {
    unsigned long now = micros();
    if (count < MAX_PERIODS) {
        periods[count++] = (uint16_t)(now - lastEdge);
    } else {
        bufFull = true;
    }
    lastEdge = now;
}

void setup() {
    Serial.begin(115200);
    pinMode(RX_PIN, INPUT);
    attachInterrupt(digitalPinToInterrupt(RX_PIN), onEdge, CHANGE);
    Serial.println(F("wire_capture ready"));
}

void loop() {
    uint16_t n;
    unsigned long last;
    noInterrupts(); n = count; last = lastEdge; interrupts();

    if (n == 0) return;

    bool gap    = (long)(micros() - last) > 5000L;
    bool full   = bufFull;
    if (!gap && !full) return;

    detachInterrupt(digitalPinToInterrupt(RX_PIN));
    noInterrupts(); n = count; interrupts();

    Serial.print(F("edges=")); Serial.print(n);
    Serial.print(F("  buf_full=")); Serial.println(full ? 1 : 0);
    Serial.print(F("periods="));
    for (uint16_t i = 1; i < n; i++) {   // skip first (garbage from startup)
        Serial.print(periods[i]);
        if (i < n - 1) Serial.print(',');
    }
    Serial.println();

    noInterrupts(); count = 0; bufFull = false; interrupts();
    attachInterrupt(digitalPinToInterrupt(RX_PIN), onEdge, CHANGE);
}
