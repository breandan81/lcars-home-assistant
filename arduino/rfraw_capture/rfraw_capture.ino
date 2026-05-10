/*
 * RF Raw Capture
 * Wiring: SYN480R DATA → Pin 2, VCC → 5V, GND → GND
 *         Tactile button → Pin 7, other leg → GND
 *
 * Hold the button and press the remote at the same time.
 * Prints raw pulse timings to serial at 9600 baud.
 */

#define RF_RECV_PIN  2
#define CAPTURE_BTN  7
#define MAX_PULSES   200

void setup() {
  Serial.begin(9600);
  pinMode(RF_RECV_PIN, INPUT);
  pinMode(CAPTURE_BTN, INPUT_PULLUP);
  Serial.println("Ready — hold button + press remote");
}

void loop() {
  // Wait for button press
  if (digitalRead(CAPTURE_BTN) == HIGH) return;

  Serial.println("Capturing...");

  static unsigned int pulses[MAX_PULSES];
  int count = 0;

  // First pulse: wait for line to go LOW (start of burst), 500ms timeout
  unsigned long t = pulseIn(RF_RECV_PIN, LOW, 500000UL);
  if (t == 0) {
    Serial.println("NOSIGNAL — no burst detected, try again");
    // debounce: wait for button release
    while (digitalRead(CAPTURE_BTN) == LOW);
    delay(200);
    return;
  }
  pulses[count++] = (unsigned int)min(t, 65535UL);

  // Capture alternating high/low until gap > 10ms = end of burst
  while (count < MAX_PULSES) {
    t = pulseIn(RF_RECV_PIN, count % 2 == 0 ? LOW : HIGH, 10000UL);
    if (t == 0) break;
    pulses[count++] = (unsigned int)min(t, 65535UL);
  }

  Serial.print("RAW ");
  Serial.print(count);
  Serial.print(" pulses:");
  for (int i = 0; i < count; i++) {
    Serial.print(' ');
    Serial.print(pulses[i]);
  }
  Serial.println();
  Serial.println("Ready — hold button + press remote");

  // Wait for button release before next capture
  while (digitalRead(CAPTURE_BTN) == LOW);
  delay(200);
}
