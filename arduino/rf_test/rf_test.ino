/*
 * RF Receiver Test — SYN480R on Pin 2
 *
 * Continuously listens and prints two things:
 *   DECODED <hex> <bits> <protocol>   — when RCSwitch recognises the signal
 *   RAW <count> <us1> <us2> …         — raw pulse timings for anything else
 *
 * Open Serial Monitor at 9600 baud and press the remote.
 */

#include <RCSwitch.h>

#define RF_RECV_PIN 2   // INT0 — must be pin 2 or 3 on Uno

RCSwitch rf;

void setup() {
  Serial.begin(9600);
  rf.enableReceive(0);  // interrupt 0 = pin 2
  Serial.println("RF test ready — press remote button");
}

void loop() {
  if (rf.available()) {
    unsigned long value = rf.getReceivedValue();
    if (value == 0) {
      // RCSwitch heard something but couldn't decode it — dump raw timings
      unsigned int* raw    = rf.getReceivedRawdata();
      unsigned int  count  = rf.getReceivedBitlength() * 2 + 2;
      Serial.print("RAW ");
      Serial.print(count);
      for (unsigned int i = 0; i < count; i++) {
        Serial.print(' ');
        Serial.print(raw[i]);
      }
      Serial.println();
    } else {
      char buf[9];
      sprintf(buf, "%08lX", value);
      Serial.print("DECODED ");
      Serial.print(buf);
      Serial.print(" bits=");
      Serial.print(rf.getReceivedBitlength());
      Serial.print(" proto=");
      Serial.println(rf.getReceivedProtocol());
    }
    rf.resetAvailable();
  }
}
