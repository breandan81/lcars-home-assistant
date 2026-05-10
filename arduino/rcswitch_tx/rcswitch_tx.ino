/*
 * RCSwitch TX Test
 * Wiring: FS1000A DATA → Pin 10, VCC → 5V, GND → GND
 * Sends code 0xABCD12 every 500ms. Power from charger, no PC needed.
 */

#include <RCSwitch.h>

#define TX_PIN 10

RCSwitch rf;

void setup() {
  Serial.begin(9600);
  rf.enableTransmit(TX_PIN);
  rf.setRepeatTransmit(10);  // send 10x per burst so RCSwitch RX sees it twice
  Serial.println("TX running");
}

void loop() {
  rf.send(0xABCD12, 24);
  Serial.println("sent");
  delay(500);
}
