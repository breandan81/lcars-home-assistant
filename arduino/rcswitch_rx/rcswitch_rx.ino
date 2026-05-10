/*
 * RCSwitch RX Test
 * Wiring: SYN480R DATA → Pin 2, VCC → 5V, GND → GND
 * Pin 2 = INT0, required by RCSwitch for interrupt-driven receive.
 * Prints decoded codes. Flash this to the receiver Uno.
 */

#include <RCSwitch.h>

#define RX_PIN 2  // INT0

RCSwitch rf;

void setup() {
  Serial.begin(9600);
  rf.enableReceive(0);  // interrupt 0 = pin 2
  Serial.println("RX ready — waiting for signal");
}

void loop() {
  if (rf.available()) {
    unsigned long value = rf.getReceivedValue();
    char buf[9];
    sprintf(buf, "%08lX", value);
    Serial.print("received: 0x");
    Serial.print(buf);
    Serial.print("  bits=");
    Serial.print(rf.getReceivedBitlength());
    Serial.print("  proto=");
    Serial.println(rf.getReceivedProtocol());
    rf.resetAvailable();
  }
}
