/*
 * ESP8266 RF Raw Capture + Replay
 * Based on approach from github.com/sillyfrog/RFreplayESP
 *
 * Wiring:
 *   RF RX module DATA → D2 (GPIO4)
 *   RF TX module DATA → D1 (GPIO5)
 *   Both modules: VCC → 3.3V or 5V, GND → GND
 *
 * Serial commands (115200 baud):
 *   R  — record: wait for signal, capture until 30ms silence
 *   P  — play:   replay the loaded raw signal
 *   L  — load:   paste a raw µs pulse sequence (H/L prefix + space-separated)
 *   D  — dump:   print captured signal for offline analysis
 *   M  — manchester: paste a hex code; sends preamble+sync+Manchester payload ×3
 *
 * Manchester timing (ceiling fan remote):
 *   T = 400µs half-period, 0=[H,L], 1=[L,H]
 *   Preamble: 860µs H, then 11× (400µs H + 400µs L)
 *   Sync gap: 5190µs L
 *   Repeats: 3× with 118452µs between start points
 */

#include <ESP8266WiFi.h>

#define RX_PIN      D2
#define TX_PIN      D1
#define MAX_PULSES  2000
#define GAP_US      30000UL   // 30ms silence = end of burst
#define TIMEOUT_US  5000000UL // 5s overall timeout waiting for signal
#define REPEATS     1

static unsigned long sig[MAX_PULSES];
static int  sigCount = 0;
static bool firstHigh = true;

// ── setup ──────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  pinMode(TX_PIN, OUTPUT);
  digitalWrite(TX_PIN, LOW);
  WiFi.mode(WIFI_OFF);
  delay(100);
  Serial.println(F("\nRF Replay — R=record  P=play  L=load  D=dump"));
}

int hexCharToNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  return -1;
}

inline bool extractBitLeftToRight(const uint8_t* data, int bitIndex) {
  int byteIndex = bitIndex / 8;
  int bitInByte = 7 - (bitIndex % 8); // MSB first
  return (data[byteIndex] >> bitInByte) & 1;
}

inline void waitForNextClock(int periodUs) {
  unsigned long start = micros() % periodUs;
  while (micros() - start < (unsigned long)periodUs) {
    yield();
  }
}

void doHunter() {
  Serial.println(F("Hunter mode: square wave preamble, pause 13 clocks, then send 65 bit payload 1 = 110, 0 = 100. Paste payload as hex (e.g. 0x123456789abcde):"));

  // wait for input then read hex string
  static char hexString[64];
  while (!Serial.available()) yield();
  Serial.readBytesUntil('\n', hexString, sizeof(hexString));
  hexString[sizeof(hexString) - 1] = 0; // ensure null termination

  //parse hex to byte array, check for non hex chars `and print error
  const int payloadBytes = 9;
  uint8_t payload[payloadBytes]; // hunter payload is 65 bits = 9 bytes (last 7 bits unused)
  for(int i = 0; i < payloadBytes; i++) {
    int hi = hexCharToNibble(hexString[i * 2]);
    int lo = hexCharToNibble(hexString[i * 2 + 1]);
    if (hi < 0 || lo < 0) {
      Serial.println(F("Invalid hex input. Please enter a valid hex string."));
      return;
    }
    payload[i] = (hi << 4) | lo;
  }
}

// ── loop ───────────────────────────────────────────────────────────────────
void loop() {
  if (!Serial.available()) return;
  char c = toupper(Serial.read());
  if      (c == 'R') doRecord();
  else if (c == 'P') doPlay();
  else if (c == 'L') doLoad();
  else if (c == 'D') doDump();
  else if (c == 'M') doManchester();
  else if (c == 'H') doHunter();
  else if (c == '?') Serial.println(F("ESP_RF"));
}

// ── record ─────────────────────────────────────────────────────────────────
void doRecord() {
  Serial.println(F("Waiting for signal — press remote button now..."));

  // Wait for first edge
  unsigned long deadline = micros() + TIMEOUT_US;
  bool idle = digitalRead(RX_PIN);
  while ((bool)digitalRead(RX_PIN) == idle) {
    if (micros() > deadline) {
      Serial.println(F("TIMEOUT — no signal detected"));
      return;
    }
    yield();
  }

  firstHigh = (digitalRead(RX_PIN) == HIGH);
  sigCount = 0;

  // Record timestamps of every state change until 30ms silence
  unsigned long last = micros();
  bool lastState = digitalRead(RX_PIN);

  while (sigCount < MAX_PULSES) {
    bool cur = digitalRead(RX_PIN);
    unsigned long now = micros();

    if (cur != lastState) {
      sig[sigCount++] = now - last;
      last = now;
      lastState = cur;
    } else if (now - last > GAP_US && sigCount > 1) {
      break; // 30ms silence after at least one transition = end of burst
    }
    yield();
  }

  if (sigCount < 10) {
    Serial.println(F("Too few pulses — try again"));
    return;
  }

  Serial.print(F("Captured "));
  Serial.print(sigCount);
  Serial.println(F(" pulses. D=dump  P=play  L=load cleaned"));
}

// ── play ───────────────────────────────────────────────────────────────────
void doPlay() {
  if (sigCount == 0) { Serial.println(F("Nothing to play.")); return; }

  Serial.print(F("Playing "));
  Serial.print(sigCount);
  Serial.print(F(" pulses × "));
  Serial.println(REPEATS);

  for (int rep = 0; rep < REPEATS; rep++) {
    bool state = firstHigh;
    unsigned long t = micros();
    for (int i = 0; i < sigCount; i++) {
      digitalWrite(TX_PIN, state ? HIGH : LOW);
      t += sig[i];
      while (micros() < t) {}  // busy-wait for precise timing
      state = !state;
    }
    digitalWrite(TX_PIN, LOW);
    delay(15);
  }
  Serial.println(F("Done — did it respond?"));
}

// ── load cleaned sequence ──────────────────────────────────────────────────
// Paste comma-separated µs values (optionally prefixed with H or L for polarity).
void doLoad() {
  Serial.println(F("Paste cleaned sequence (optional H/L prefix, comma-separated µs):"));
  while (!Serial.available()) yield();
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) { Serial.println(F("Empty — cancelled.")); return; }

  int pos = 0;
  if (line[0] == 'H' || line[0] == 'h') { firstHigh = true;  pos = 1; }
  else if (line[0] == 'L' || line[0] == 'l') { firstHigh = false; pos = 1; }

  sigCount = 0;
  while (pos < (int)line.length() && sigCount < MAX_PULSES) {
    while (pos < (int)line.length() && (line[pos] == ' ' || line[pos] == ',')) pos++;
    if (pos >= (int)line.length()) break;
    int end = pos;
    while (end < (int)line.length() && line[end] != ',' && line[end] != ' ') end++;
    sig[sigCount++] = (unsigned long)line.substring(pos, end).toInt();
    pos = end + 1;
  }

  if (sigCount < 4) { Serial.println(F("Too few values.")); return; }
  Serial.print(F("Loaded "));
  Serial.print(sigCount);
  Serial.println(F(" pulses. P=play"));
}

// ── Manchester transmit ────────────────────────────────────────────────────
// Busy-wait precise delay using micros().
static void txDelay(unsigned long us) {
  unsigned long t = micros();
  while (micros() - t < us) {}
}

// Send one Manchester half-period at given level.
static void txHalf(bool high, unsigned long T) {
  digitalWrite(TX_PIN, high ? HIGH : LOW);
  txDelay(T);
}

// Send one Manchester-encoded bit (convention: 0=[H,L], 1=[L,H]).
static void txBit(bool bit, unsigned long T) {
  txHalf(!bit, T);   // first half
  txHalf(bit,  T);   // second half — opposite, mandatory mid-bit transition
}

// Send full preamble + sync gap.
static void txPreamble() {
  // First HIGH pulse ~2T (leader)
  txHalf(true,  860);
  // 11 × (H + L) alternating preamble bits (all-zero Manchester)
  for (int i = 0; i < 11; i++) {
    txHalf(true,  400);
    txHalf(false, 400);
  }
  // Sync gap: LOW ~5190µs
  txHalf(false, 5190);
}

// Transmit Manchester payload from hex string, preamble + sync included.
// Repeats 3× with ~118452µs between start points (measured from remote).
void doManchester() {
  Serial.println(F("Paste hex code (e.g. 934924d36d26924da6db4d2480):"));
  while (!Serial.available()) yield();
  String hex = Serial.readStringUntil('\n');
  hex.trim();
  if (hex.length() == 0) { Serial.println(F("Empty — cancelled.")); return; }

  // Parse hex into bytes
  uint8_t buf[64];
  int nbytes = 0;
  for (int i = 0; i + 1 < (int)hex.length() && nbytes < 64; i += 2) {
    char tmp[3] = { hex[i], hex[i+1], 0 };
    buf[nbytes++] = (uint8_t)strtol(tmp, nullptr, 16);
  }
  int nbits = nbytes * 8;

  Serial.print(F("Sending "));
  Serial.print(nbits);
  Serial.println(F(" bits × 3 repeats..."));

  unsigned long frame_start = micros();
  for (int rep = 0; rep < 3; rep++) {
    txPreamble();
    // Send bits MSB-first from each byte
    for (int bi = 0; bi < nbytes; bi++) {
      for (int bit = 7; bit >= 0; bit--) {
        txBit((buf[bi] >> bit) & 1, 400);
      }
    }
    digitalWrite(TX_PIN, LOW);

    if (rep < 2) {
      // Wait until 118452µs after this frame's start before next frame
      unsigned long elapsed = micros() - frame_start;
      if (elapsed < 118452UL)
        txDelay(118452UL - elapsed);
      frame_start += 118452UL;
    }
  }

  digitalWrite(TX_PIN, LOW);
  Serial.println(F("Done."));
}

// ── dump ───────────────────────────────────────────────────────────────────
void doDump() {
  if (sigCount == 0) { Serial.println(F("Nothing captured.")); return; }
  Serial.print(F("RFRAW firstHigh="));
  Serial.print(firstHigh ? 1 : 0);
  Serial.print(F(" count="));
  Serial.print(sigCount);
  Serial.print(F(" pulses="));
  for (int i = 0; i < sigCount; i++) {
    if (i) Serial.print(' ');
    Serial.print(sig[i]);
  }
  Serial.println();
}
