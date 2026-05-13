#include "HunterFan.h"

// ── Platform shims ────────────────────────────────────────────────────────────

#if defined(ESP8266)
#  define HF_WDT_DISABLE() ESP.wdtDisable()
#  define HF_WDT_ENABLE()  ESP.wdtEnable(2000)
#else
#  define HF_WDT_DISABLE()
#  define HF_WDT_ENABLE()
#endif

// ── ISR trampoline ────────────────────────────────────────────────────────────

static HunterFan* _hfInstance = nullptr;

static void HF_IRAM _hfISR() {
    if (_hfInstance) _hfInstance->_onEdge();
}

// ── Construction / begin ──────────────────────────────────────────────────────

HunterFan::HunterFan(uint8_t txPin, uint8_t rxPin)
    : _txPin(txPin), _rxPin(rxPin) {}

void HunterFan::begin() {
    if (_txPin != 0xFF) {
        pinMode(_txPin, OUTPUT);
        digitalWrite(_txPin, LOW);
    }
    if (_rxPin != 0xFF) {
        _hfInstance = this;
        pinMode(_rxPin, INPUT);
        attachInterrupt(digitalPinToInterrupt(_rxPin), _hfISR, CHANGE);
    }
}

void HF_IRAM HunterFan::_onEdge() {
    _pulseStamp = micros();
    _newPulse   = true;
}

// ── Receive ───────────────────────────────────────────────────────────────────

bool HunterFan::_getPulse(unsigned long& stamp) {
    noInterrupts();
    bool got = _newPulse;
    if (got) { stamp = _pulseStamp; _newPulse = false; }
    interrupts();
    return got;
}

bool HunterFan::receive(uint8_t* data, uint8_t maxBytes, uint8_t& bits,
                        uint32_t timeoutMs) {
    memset(data, 0, maxBytes);
    bits = 0;

    const uint16_t t1min  = clkUs - clkTolUs;
    const uint16_t t1max  = clkUs + clkTolUs;
    const uint16_t t2min  = clkUs * 2 - clkTolUs * 2;
    const uint16_t t2max  = clkUs * 2 + clkTolUs * 2;
    const uint32_t ancMin = (uint32_t)clkUs * 13 - (uint32_t)clkTolUs * 13;
    const uint32_t ancMax = (uint32_t)clkUs * 13 + (uint32_t)clkTolUs * 13;

    unsigned long last = 0, stamp;
    int syncCount = 0;

    noInterrupts(); _newPulse = false; interrupts();
    HF_WDT_DISABLE();

    // 1 — sync: wait for minSync consecutive 1T pulses
    unsigned long deadline = millis() + timeoutMs;
    while (millis() < deadline) {
        if (!_getPulse(stamp)) continue;
        long p = (long)(stamp - last);
        last = stamp;
        if (p >= t1min && p <= t1max) { if (++syncCount >= minSync) break; }
        else syncCount = 0;
    }
    if (syncCount < minSync) { HF_WDT_ENABLE(); return false; }

    // 2 — anchor: first pulse ≥13T after sync
    deadline = millis() + 100;
    bool anchorFound = false;
    while (millis() < deadline) {
        if (!_getPulse(stamp)) continue;
        long p = (long)(stamp - last);
        last = stamp;
        if ((uint32_t)p >= ancMin && (uint32_t)p <= ancMax) { anchorFound = true; break; }
        if (p < t1min || p > t1max) { HF_WDT_ENABLE(); return false; }
    }
    if (!anchorFound) { HF_WDT_ENABLE(); return false; }

    // 3 — data: PWM pairs until inter-frame gap
    const uint8_t maxBits = maxBytes * 8;
    while (bits < maxBits) {
        // first half: pulse width encodes bit value
        while (!_getPulse(stamp)) {
            if ((long)(micros() - last) > (long)ancMin) {
                HF_WDT_ENABLE();
                return bits > 0;
            }
        }
        long p1 = (long)(stamp - last);
        last = stamp;
        bool bitVal;
        if      (p1 >= t2min && p1 <= t2max) bitVal = true;
        else if (p1 >= t1min && p1 <= t1max) bitVal = false;
        else { HF_WDT_ENABLE(); return false; }
        _setBit(data, bits++, bitVal);

        // second half: complement (1→1T, 0→2T), or EOP gap
        unsigned long t0 = micros();
        while (!_getPulse(stamp)) {
            if ((long)(micros() - t0) > (long)ancMin) {
                HF_WDT_ENABLE();
                return bits > 0;
            }
        }
        long p2 = (long)(stamp - last);
        last = stamp;
        bool valid = bitVal ? (p2 >= t1min && p2 <= t1max)
                            : (p2 >= t2min && p2 <= t2max);
        if (!valid) { HF_WDT_ENABLE(); return false; }
    }

    HF_WDT_ENABLE();
    return bits > 0;
}

// ── Transmit ──────────────────────────────────────────────────────────────────

void HF_IRAM HunterFan::_waitForNextClock() {
    unsigned long entry = micros();
    unsigned long phase = entry % clkUs;
    unsigned long next  = entry + (clkUs - phase);
    while ((long)(micros() - next) < 0) {}
}

void HF_IRAM HunterFan::_sendOne() {
    // 1-bit: 2T HIGH + 1T LOW
    _waitForNextClock();
    digitalWrite(_txPin, HIGH);
    _waitForNextClock();
    _waitForNextClock();
    digitalWrite(_txPin, LOW);
}

void HF_IRAM HunterFan::_sendZero() {
    // 0-bit: 1T HIGH + 2T LOW
    _waitForNextClock();
    digitalWrite(_txPin, HIGH);
    _waitForNextClock();
    digitalWrite(_txPin, LOW);
    _waitForNextClock();
}

void HF_IRAM HunterFan::_sendFrame(const uint8_t* data, uint8_t bits) {
    // preamble
    for (uint8_t i = 0; i < preamblePairs; i++) {
        _waitForNextClock();
        digitalWrite(_txPin, HIGH);
        _waitForNextClock();
        digitalWrite(_txPin, LOW);
    }
    // anchor: anchorClocks×T LOW, then first bit adds one more T = (anchorClocks+1)T total
    digitalWrite(_txPin, LOW);
    for (uint8_t i = 0; i < anchorClocks; i++) _waitForNextClock();
    // data
    for (uint8_t i = 0; i < bits; i++) {
        if (_getBit(data, i)) _sendOne();
        else                  _sendZero();
    }
}

void HunterFan::send(const uint8_t* data, uint8_t bits) {
    HF_WDT_DISABLE();
    for (uint8_t i = 0; i < repeats; i++) {
        if (disableInterruptsDuringTx) noInterrupts();
        _sendFrame(data, bits);
        if (disableInterruptsDuringTx) interrupts();
        if (i < repeats - 1) delayMicroseconds(frameGapUs);
    }
    digitalWrite(_txPin, LOW);
    HF_WDT_ENABLE();
}

void HunterFan::sendHex(const char* hexStr, uint8_t bits) {
    uint8_t data[32] = {};
    if (_fromHex(hexStr, data, sizeof(data))) send(data, bits);
}

// ── Utilities ─────────────────────────────────────────────────────────────────

uint8_t HunterFan::_reverseBits(uint8_t b) {
    b = (b & 0xF0) >> 4 | (b & 0x0F) << 4;
    b = (b & 0xCC) >> 2 | (b & 0x33) << 2;
    b = (b & 0xAA) >> 1 | (b & 0x55) << 1;
    return b;
}

bool HunterFan::_getBit(const uint8_t* d, uint8_t i) {
    return (d[i / 8] >> (i % 8)) & 1;
}

void HunterFan::_setBit(uint8_t* d, uint8_t i, bool v) {
    if (v) d[i / 8] |=  (1u << (i % 8));
    else   d[i / 8] &= ~(1u << (i % 8));
}

int HunterFan::_hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + c - 'a';
    if (c >= 'A' && c <= 'F') return 10 + c - 'A';
    return -1;
}

// Hex string → internal byte array (reverseBits applied to each byte).
// Round-trips correctly with toHex().
bool HunterFan::_fromHex(const char* s, uint8_t* out, uint8_t maxBytes) {
    uint8_t n = 0;
    while (s[0] && s[1] && n < maxBytes) {
        int hi = _hexNibble(s[0]), lo = _hexNibble(s[1]);
        if (hi < 0 || lo < 0) return false;
        out[n++] = _reverseBits((uint8_t)((hi << 4) | lo));
        s += 2;
    }
    return n > 0;
}

const char* HunterFan::toHex(const uint8_t* data, uint8_t bytes) {
    static char buf[65];
    uint8_t n = bytes < 32 ? bytes : 32;
    for (uint8_t i = 0; i < n; i++)
        snprintf(buf + i * 2, 3, "%02X", _reverseBits(data[i]));
    buf[n * 2] = '\0';
    return buf;
}
