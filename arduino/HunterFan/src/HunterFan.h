#pragma once
#include <Arduino.h>

// Platform IRAM attribute — keeps timing-critical code out of flash cache
#if defined(ESP8266)
#  define HF_IRAM ICACHE_RAM_ATTR
#elif defined(ESP32)
#  define HF_IRAM IRAM_ATTR
#else
#  define HF_IRAM
#endif

class HunterFan {
public:
    // ── Protocol timing ───────────────────────────────────────────────────────
    // All times in µs. Override before begin() to adapt to other protocols.
    uint16_t clkUs         = 400;   // nominal bit-clock period
    uint16_t clkTolUs      = 45;    // ± receive tolerance
    uint8_t  preamblePairs = 60;    // alternating pulses before anchor (AGC settling)
    uint8_t  anchorClocks  = 12;    // LOW clocks in anchor gap; total anchor = (anchorClocks+1)×clkUs
    uint8_t  minSync       = 16;    // consecutive 1T pulses required to lock sync
    uint16_t frameGapUs    = 26000; // µs gap between repeated frames
    uint8_t  repeats       = 3;     // how many times to repeat each transmission

    // Disabling interrupts during TX prevents WiFi ISR jitter on ESP but breaks
    // micros() on AVR (Timer0 overflows stack up, causing _waitForNextClock to
    // hang after ~2ms). On AVR the only relevant ISR is Timer0 (~1µs), which is
    // well within the ±45µs tolerance, so leave interrupts enabled everywhere.
    bool disableInterruptsDuringTx = false;

    // ── Construction ─────────────────────────────────────────────────────────
    // rxPin = 0xFF disables receive (TX-only mode).
    // Both txPin and rxPin must be interrupt-capable for receive to work.
    HunterFan(uint8_t txPin, uint8_t rxPin = 0xFF);
    void begin();

    // ── Transmit ─────────────────────────────────────────────────────────────

    // Send raw bytes in wire bit-order (the same format receive() fills).
    void send(const uint8_t* data, uint8_t bits);

    // Send from a hex string, e.g. sendHex("A6FF346CBB18067F80", 66).
    // The string format matches what toHex() produces, so a capture can be
    // replayed verbatim.
    void sendHex(const char* hexStr, uint8_t bits);

    // ── Receive ──────────────────────────────────────────────────────────────

    // Block until one packet is decoded or timeoutMs elapses.
    // Returns true on success; fills data[] and sets bits.
    // data must be at least (bits+7)/8 bytes; maxBytes caps storage.
    bool receive(uint8_t* data, uint8_t maxBytes, uint8_t& bits,
                 uint32_t timeoutMs = 2000);

    // ── Utility ──────────────────────────────────────────────────────────────

    // Format decoded bytes as a hex string (static buffer — not reentrant).
    static const char* toHex(const uint8_t* data, uint8_t bytes);

    // ── Internal ISR trampoline ───────────────────────────────────────────────
    // Called from a global ISR; do not call directly.
    void _onEdge();

private:
    uint8_t  _txPin;
    uint8_t  _rxPin;
    volatile bool          _newPulse   = false;
    volatile unsigned long _pulseStamp = 0;

    HF_IRAM void _waitForNextClock();
    HF_IRAM void _sendFrame(const uint8_t* data, uint8_t bits);
    HF_IRAM void _sendOne();
    HF_IRAM void _sendZero();

    bool _getPulse(unsigned long& stamp);

    static bool    _getBit(const uint8_t* d, uint8_t i);
    static void    _setBit(uint8_t* d, uint8_t i, bool v);
    static uint8_t _reverseBits(uint8_t b);
    static int     _hexNibble(char c);
    static bool    _fromHex(const char* s, uint8_t* out, uint8_t maxBytes);
};
