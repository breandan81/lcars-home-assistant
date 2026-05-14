// Bare toggle test — no library, just _waitForNextClock logic on Pin 10
const uint8_t PIN = 10;
const unsigned long CLK = 400;

void waitNextClock() {
    delayMicroseconds(CLK);
}

void setup() {
    pinMode(PIN, OUTPUT);
    digitalWrite(PIN, LOW);
}

void loop() {
    // Send 120 preamble toggles (60 pairs) then pause 5ms
    for (int i = 0; i < 120; i++) {
        waitNextClock();
        digitalWrite(PIN, i & 1 ? LOW : HIGH);
    }
    digitalWrite(PIN, LOW);
    delay(5);
}
