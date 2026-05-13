/*
 * hunter_rx_debug — Hunter fan RX decoder with stage diagnostics
 * Pin 2 (INT0), 115200 baud.
 */

#define RX_PIN 2

static const long T       = 400;
static const long TOL     = 45;
static const long T1_MIN  = T   - TOL;
static const long T1_MAX  = T   + TOL;
static const long T2_MIN  = T*2 - TOL*2;
static const long T2_MAX  = T*2 + TOL*2;
static const long ANC_MIN = T*13 - TOL*13;
static const long ANC_MAX = T*13 + TOL*13;
static const int  MIN_SYNC    = 16;
static const int  PACKET_BYTES = 16;

volatile bool          newPulse  = false;
volatile unsigned long pulseStamp = 0;

void onEdge() { pulseStamp = micros(); newPulse = true; }

static uint8_t pkt[PACKET_BYTES];

static void setBit(int idx, bool v) {
  if (idx / 8 >= PACKET_BYTES) return;
  if (v) pkt[idx/8] |=  (1 << (idx % 8));
  else   pkt[idx/8] &= ~(1 << (idx % 8));
}
static uint8_t reverseBits(uint8_t b) {
  b = (b & 0xF0) >> 4 | (b & 0x0F) << 4;
  b = (b & 0xCC) >> 2 | (b & 0x33) << 2;
  b = (b & 0xAA) >> 1 | (b & 0x55) << 1;
  return b;
}
static inline bool is1T(long p) { return p >= T1_MIN && p <= T1_MAX; }
static inline bool is2T(long p) { return p >= T2_MIN && p <= T2_MAX; }
static inline bool isAnc(long p){ return p >= ANC_MIN && p <= ANC_MAX; }

// Grab pulse atomically (ISR may fire between instructions on AVR)
static bool getPulse(unsigned long &stamp) {
  noInterrupts();
  bool got = newPulse;
  if (got) { stamp = pulseStamp; newPulse = false; }
  interrupts();
  return got;
}

static int hunterRead() {
  memset(pkt, 0, sizeof(pkt));
  unsigned long last = 0;
  int syncCount = 0;
  unsigned long stamp;
  noInterrupts(); newPulse = false; interrupts();

  // 1 — sync
  unsigned long deadline = millis() + 2000UL;
  while (millis() < deadline) {
    if (!getPulse(stamp)) continue;
    long period = (long)(stamp - last);
    last = stamp;
    if (is1T(period)) { if (++syncCount >= MIN_SYNC) break; }
    else              syncCount = 0;
  }
  if (syncCount < MIN_SYNC) {
    Serial.print(F("FAIL sync=")); Serial.println(syncCount);
    return 0;
  }
  Serial.print(F("sync OK  "));

  // 2 — anchor
  bool anchorFound = false;
  deadline = millis() + 100UL;
  while (millis() < deadline) {
    if (!getPulse(stamp)) continue;
    long period = (long)(stamp - last);
    last = stamp;
    if (isAnc(period)) { anchorFound = true; break; }
    if (!is1T(period)) {
      Serial.print(F("FAIL anchor bad pulse=")); Serial.println(period);
      return 0;
    }
  }
  if (!anchorFound) {
    Serial.println(F("FAIL anchor timeout"));
    return 0;
  }
  Serial.print(F("anchor OK  "));

  // 3 — bits
  int bitCount = 0;
  while (true) {
    // first half (HIGH pulse)
    while (!getPulse(stamp)) {
      if ((long)(micros() - last) > ANC_MIN) {
        Serial.print(F("EOP bits=")); Serial.println(bitCount);
        return bitCount;
      }
    }
    long period = (long)(stamp - last);
    last = stamp;

    bool bit;
    if      (is2T(period)) bit = true;
    else if (is1T(period)) bit = false;
    else {
      Serial.print(F("FAIL bit1 period=")); Serial.print(period);
      Serial.print(F(" at bit")); Serial.println(bitCount);
      return 0;
    }
    setBit(bitCount++, bit);

    // second half (LOW pulse)
    unsigned long t0 = micros();
    while (!getPulse(stamp)) {
      if ((long)(micros() - t0) > ANC_MIN) {
        Serial.print(F("EOP(inner) bits=")); Serial.println(bitCount);
        return bitCount;
      }
    }
    period = (long)(stamp - last);
    last = stamp;

    if (bit && !is1T(period)) {
      Serial.print(F("FAIL bit0_lo period=")); Serial.print(period);
      Serial.print(F(" at bit")); Serial.println(bitCount);
      return 0;
    }
    if (!bit && !is2T(period)) {
      Serial.print(F("FAIL bit1_lo period=")); Serial.print(period);
      Serial.print(F(" at bit")); Serial.println(bitCount);
      return 0;
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(RX_PIN), onEdge, CHANGE);
  Serial.println(F("Hunter RX debug ready"));
}

void loop() {
  int bits = hunterRead();
  if (bits <= 0) return;

  char buf[3];
  int byteCount = (bits + 7) / 8;
  Serial.print(F("RECV "));
  Serial.print(bits);
  Serial.print(F("b  "));
  for (int i = 0; i < byteCount; i++) {
    snprintf(buf, sizeof(buf), "%02X", reverseBits(pkt[i]));
    Serial.print(buf);
  }
  Serial.println();
}
