/*
 * IR Pin Diagnostic — reads pin 11 raw, reports idle level and transitions.
 * VS1838B output is HIGH when idle, pulses LOW when receiving 38kHz IR.
 */
#define IR_PIN 11

void setup() {
  Serial.begin(9600);
  pinMode(IR_PIN, INPUT);
  Serial.println("IR diag ready — watching pin 11");
  Serial.print("Idle level: ");
  Serial.println(digitalRead(IR_PIN) ? "HIGH (correct)" : "LOW (bad wiring or floating)");
}

void loop() {
  unsigned long start = millis();
  int transitions = 0;
  int lastState = digitalRead(IR_PIN);
  while (millis() - start < 200) {
    int s = digitalRead(IR_PIN);
    if (s != lastState) { transitions++; lastState = s; }
  }
  if (transitions > 0) {
    Serial.print("TRANSITIONS: ");
    Serial.print(transitions);
    Serial.println(" in 200ms — IR signal seen on pin 11");
  }
}
