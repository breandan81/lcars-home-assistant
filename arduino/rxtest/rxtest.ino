/*
 * RF RX Test — RadioHead RH_ASK
 * Wiring: SYN480R DATA → Pin 11, VCC → 5V, GND → GND
 * Prints anything received. Flash this to the receiver Uno.
 */

#include <RH_ASK.h>
#include <SPI.h>

// RH_ASK(speed, rxPin, txPin, pttPin)
RH_ASK driver(2000, 11, 255, 255);  // rx on pin 11, tx unused (255)

void setup() {
  Serial.begin(9600);
  if (!driver.init())
    Serial.println("init failed");
  else
    Serial.println("RX ready — waiting for packets");
}

void loop() {
  uint8_t buf[32];
  uint8_t buflen = sizeof(buf);
  if (driver.recv(buf, &buflen)) {
    buf[buflen] = '\0';
    Serial.print("received: ");
    Serial.println((char *)buf);
  }
}
