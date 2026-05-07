/*
 * LCARS IR Blaster — Arduino Uno / clone over USB serial
 *
 * Library (install via Arduino IDE → Manage Libraries):
 *   "IRremote" by shirriff — install version 2.x ONLY (not 3.x/4.x, different API)
 *
 * Wiring:
 *   IR LED anode  → 100Ω resistor → Pin 3  (must be a PWM pin)
 *   IR LED cathode → GND
 *   IR Receiver (TSOP38238 / VS1838B) DATA → Pin 11
 *   IR Receiver VCC → 5V,  GND → GND
 *
 * Serial protocol — 9600 baud, commands are newline-terminated:
 *   PING\n                       → PONG\n
 *   SEND NEC 807F817E 32\n       → OK\n  or  ERROR msg\n
 *   LEARN\n                      → CODE NEC 807F817E 32\n  or  TIMEOUT\n
 *
 * Note: IRremote v2 uses Timer 2 for both send and receive.
 * The sketch disables the receiver before sending and re-enables it only
 * during LEARN, so they never conflict.
 */

#include <IRremote.h>

#define RECV_PIN 11   // Any digital pin. Keep away from Pin 3.

IRsend   irsend;       // Hardwired to Pin 3 on Uno in IRremote v2
IRrecv   irrecv(RECV_PIN);
decode_results results;

// ─── Setup ──────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  // Leave irrecv disabled — enabling it blocks irsend's timer.
}

// ─── Loop ───────────────────────────────────────────────────────────────────
void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) handleCommand(line);
  }
}

// ─── Dispatch ────────────────────────────────────────────────────────────────
void handleCommand(const String& cmd) {
  if (cmd == "PING") {
    Serial.println("PONG");
  } else if (cmd == "LEARN") {
    doLearn();
  } else if (cmd.startsWith("SEND ")) {
    doSend(cmd);
  } else {
    Serial.println("ERROR unknown command");
  }
}

// ─── SEND ────────────────────────────────────────────────────────────────────
// Input:  SEND <PROTOCOL> <HEXCODE> <BITS>
// e.g.:   SEND NEC 807F817E 32
void doSend(const String& cmd) {
  // Tokenise
  int p1 = 5;
  int p2 = cmd.indexOf(' ', p1);
  if (p2 < 0) { Serial.println("ERROR malformed"); return; }

  int p3 = cmd.indexOf(' ', p2 + 1);
  if (p3 < 0) { Serial.println("ERROR malformed"); return; }

  String protocol = cmd.substring(p1, p2);
  protocol.toUpperCase();

  String hexStr  = cmd.substring(p2 + 1, p3);
  String bitsStr = cmd.substring(p3 + 1);

  unsigned long code = strtoul(hexStr.c_str(), NULL, 16);
  int bits = bitsStr.toInt();
  if (bits == 0) bits = 32;

  irrecv.disableIRIn(); // Must be off while sending

  if (protocol == "NEC") {
    irsend.sendNEC(code, bits);
  } else if (protocol == "SAMSUNG") {
    irsend.sendSAMSUNG(code, bits);
  } else if (protocol == "SONY") {
    // Sony spec requires ≥3 transmissions
    for (int i = 0; i < 3; i++) {
      irsend.sendSony(code, bits);
      delay(40);
    }
  } else if (protocol == "RC5") {
    irsend.sendRC5(code, bits);
  } else if (protocol == "RC6") {
    irsend.sendRC6(code, bits);
  } else if (protocol == "LG") {
    irsend.sendLG(code, bits);
  } else if (protocol == "PANASONIC") {
    irsend.sendPanasonic(code >> 16, code & 0xFFFF);
  } else if (protocol == "SHARP") {
    irsend.sendSharp(code >> 8, code & 0xFF);
  } else {
    // Unknown — attempt NEC as a fallback
    irsend.sendNEC(code, bits);
  }

  Serial.println("OK");
}

// ─── LEARN ──────────────────────────────────────────────────────────────────
void doLearn() {
  irrecv.enableIRIn();
  unsigned long deadline = millis() + 10000UL;

  while (millis() < deadline) {
    if (irrecv.decode(&results)) {
      unsigned long value = results.value;

      irrecv.resume();

      // Skip repeat codes — wait for the real code
      if (value == 0xFFFFFFFFUL || value == 0) {
        continue;
      }

      irrecv.disableIRIn();

      char hexbuf[9];
      sprintf(hexbuf, "%08lX", value);

      Serial.print("CODE ");
      Serial.print(protocolName(results.decode_type));
      Serial.print(" ");
      Serial.print(hexbuf);
      Serial.print(" ");
      Serial.println(results.bits);
      return;
    }
    delay(10);
  }

  irrecv.disableIRIn();
  Serial.println("TIMEOUT");
}

// ─── Protocol name lookup ────────────────────────────────────────────────────
const char* protocolName(int type) {
  switch (type) {
    case NEC:       return "NEC";
    case SONY:      return "SONY";
    case RC5:       return "RC5";
    case RC6:       return "RC6";
    case SAMSUNG:   return "SAMSUNG";
    case LG:        return "LG";
    case PANASONIC: return "PANASONIC";
    case SHARP:     return "SHARP";
    default:        return "UNKNOWN";
  }
}
