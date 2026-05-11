/*
 * ESP8266 RF Raw Capture + Replay Test
 *
 * Wiring:
 *   RF RX module DATA → D2 (GPIO4)
 *   RF TX module DATA → D1 (GPIO5)
 *   Both modules: VCC → 3.3V or 5V, GND → GND
 *
 * Serial commands (115200 baud):
 *   R  — record: pre-pulse TX to settle AGC, then capture ~4s of signal
 *        (hold the remote button for the full 4s to get multiple repetitions)
 *   P  — play:   replay the loaded pulse sequence 5×
 *   L  — load:   paste a cleaned pulse sequence from the analysis script
 *   D  — dump:   print raw capture for offline analysis
 *
 * Workflow:
 *   1. Press R, then immediately hold remote button for 4s
 *   2. Copy the DUMP output into rf_analyze.py
 *   3. Run rf_analyze.py to extract the clean repeating pattern
 *   4. Paste the output back with the L command
 *   5. Press P to test replay
 */

#include <ESP8266WiFi.h>

#define RX_PIN      D2
#define TX_PIN      D1
#define AGC_PULSES  8        // short bursts to prime AGC before capture
#define AGC_HALF_US 300      // half-period of priming pulses (µs)
#define CAPTURE_MS  4000     // capture window (ms) — hold button this long
#define MAX_PULSES  1200     // fits ~10 NEC-style frames
#define GAP_US      12000    // >12ms silence = end of burst / between frames
#define REPEATS     5

static uint16_t raw[MAX_PULSES];
static int      rawCount  = 0;
static bool     firstHigh = true;

static uint16_t clean[MAX_PULSES];
static int      cleanCount = 0;
static bool     hasClean   = false;

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

// ── loop ───────────────────────────────────────────────────────────────────
void loop() {
  if (!Serial.available()) return;
  char c = toupper(Serial.read());
  if      (c == 'R') doRecord();
  else if (c == 'P') doPlay();
  else if (c == 'L') doLoad();
  else if (c == 'D') doDump();
}

// ── prime AGC ──────────────────────────────────────────────────────────────
void primeAGC() {
  // Send a few short carrier bursts so the RX AGC settles before we listen.
  for (int i = 0; i < AGC_PULSES; i++) {
    digitalWrite(TX_PIN, HIGH);
    delayMicroseconds(AGC_HALF_US);
    digitalWrite(TX_PIN, LOW);
    delayMicroseconds(AGC_HALF_US);
  }
}

// ── record ─────────────────────────────────────────────────────────────────
void doRecord() {
  Serial.println(F("Priming AGC..."));
  primeAGC();
  delay(5);   // brief gap so TX burst doesn't bleed into capture

  Serial.print(F("Capturing for "));
  Serial.print(CAPTURE_MS / 1000);
  Serial.println(F("s — hold remote button NOW..."));

  rawCount = 0;

  // Wait for first edge (up to 2s after priming)
  int idle = digitalRead(RX_PIN);
  unsigned long start = millis();
  while (digitalRead(RX_PIN) == idle) {
    if (millis() - start > 2000) { Serial.println(F("TIMEOUT — no signal")); return; }
    yield();
  }
  firstHigh = (digitalRead(RX_PIN) == HIGH);

  // Capture until window expires, recording pulse widths
  bool state = firstHigh;
  unsigned long deadline = millis() + CAPTURE_MS;
  while (rawCount < MAX_PULSES && millis() < deadline) {
    unsigned long t = pulseIn(RX_PIN, state ? HIGH : LOW, GAP_US);
    if (t == 0) {
      // gap — wait for next burst
      state = firstHigh;
      continue;
    }
    raw[rawCount++] = (uint16_t)min(t, 65535UL);
    state = !state;
    yield();
  }

  if (rawCount < 10) {
    Serial.println(F("Too few pulses — try again"));
    return;
  }

  Serial.print(F("Captured "));
  Serial.print(rawCount);
  Serial.println(F(" pulses. D=dump  P=play raw  L=load cleaned"));
}

// ── play ───────────────────────────────────────────────────────────────────
void doPlay() {
  uint16_t *seq   = hasClean ? clean  : raw;
  int       count = hasClean ? cleanCount : rawCount;
  bool      fh    = firstHigh;

  if (count == 0) { Serial.println(F("Nothing to play.")); return; }

  Serial.print(F("Playing "));
  Serial.print(count);
  Serial.print(F(" pulses × "));
  Serial.print(REPEATS);
  Serial.println(hasClean ? F("× (clean sequence)...") : F("× (raw — use L to load clean)..."));

  for (int rep = 0; rep < REPEATS; rep++) {
    bool state = fh;
    for (int i = 0; i < count; i++) {
      digitalWrite(TX_PIN, state ? HIGH : LOW);
      delayMicroseconds(seq[i]);
      state = !state;
    }
    digitalWrite(TX_PIN, LOW);
    delay(15);
  }
  Serial.println(F("Done — did it respond?"));
}

// ── load cleaned sequence ──────────────────────────────────────────────────
// Paste a line of space-separated µs values from rf_analyze.py output.
// First token must be H or L indicating polarity of first pulse.
void doLoad() {
  Serial.println(F("Paste cleaned sequence (H/L polarity + space-separated µs), end with newline:"));
  while (!Serial.available()) yield();
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) { Serial.println(F("Empty — cancelled.")); return; }

  cleanCount = 0;
  int pos = 0;

  // First token: polarity
  if (line[0] == 'H' || line[0] == 'h') { firstHigh = true;  pos = 2; }
  else if (line[0] == 'L' || line[0] == 'l') { firstHigh = false; pos = 2; }
  else { pos = 0; }  // no polarity prefix, assume firstHigh unchanged

  while (pos < (int)line.length() && cleanCount < MAX_PULSES) {
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    if (pos >= (int)line.length()) break;
    int end = line.indexOf(' ', pos);
    if (end < 0) end = line.length();
    clean[cleanCount++] = (uint16_t)line.substring(pos, end).toInt();
    pos = end + 1;
  }

  if (cleanCount < 4) { Serial.println(F("Too few values.")); return; }
  hasClean = true;
  Serial.print(F("Loaded "));
  Serial.print(cleanCount);
  Serial.println(F(" pulses. P=play"));
}

// ── dump raw capture ───────────────────────────────────────────────────────
void doDump() {
  if (rawCount == 0) { Serial.println(F("Nothing captured.")); return; }
  Serial.print(F("RFRAW firstHigh="));
  Serial.print(firstHigh ? 1 : 0);
  Serial.print(F(" count="));
  Serial.print(rawCount);
  Serial.print(F(" pulses="));
  for (int i = 0; i < rawCount; i++) {
    if (i) Serial.print(' ');
    Serial.print(raw[i]);
  }
  Serial.println();
}
