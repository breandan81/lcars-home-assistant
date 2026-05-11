/*
 * IRremote v3 API test — decode() with no arg, read decodedIRData.
 * VS1838B DATA → pin 11, VCC → 5V, GND → GND
 */
#include <IRremote.h>

#define IR_RECV_PIN 11
IRrecv irrecv(IR_RECV_PIN);

void setup() {
  Serial.begin(9600);
  irrecv.enableIRIn();
  Serial.println("IR ready (v3 API) — press a remote button");
}

void loop() {
  if (irrecv.decode()) {
    IRData &d = irrecv.decodedIRData;
    char buf[9];
    sprintf(buf, "%08lX", (unsigned long)d.decodedRawData);
    Serial.print("proto=");
    Serial.print(d.protocol);
    Serial.print(" val=0x");
    Serial.print(buf);
    Serial.print(" bits=");
    Serial.print(d.numberOfBits);
    Serial.print(" addr=0x");
    Serial.print(d.address, HEX);
    Serial.print(" cmd=0x");
    Serial.println(d.command, HEX);
    irrecv.resume();
  }
}
