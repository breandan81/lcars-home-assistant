/*
 * RF TX Test — RadioHead RH_ASK
 * Wiring: FS1000A DATA → Pin 12, VCC → 5V, GND → GND
 * Sends "HELLO" every second. Flash this to the transmitter Uno.
 */

#include <RH_ASK.h>
#include <SPI.h>

// RH_ASK(speed, rxPin, txPin, pttPin)
RH_ASK driver(2000, 255, 12, 255);  // rx unused (255), tx on pin 12

void setup() {
  Serial.begin(9600);
  if (!driver.init())
    Serial.println("init failed");
  else
    Serial.println("TX ready — sending HELLO every second");
}

void loop() {
  const char *msg = "HELLO";
  driver.send((uint8_t *)msg, strlen(msg));
  driver.waitPacketSent();
  Serial.println("sent: HELLO");
  delay(1000);
}
