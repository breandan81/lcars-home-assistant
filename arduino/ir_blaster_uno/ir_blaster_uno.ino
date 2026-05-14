/*
 * LCARS IR + RF Blaster — Arduino Uno / clone over USB serial
 *
 * Libraries (Arduino IDE → Manage Libraries):
 *   "IRremote" by shirriff — version 2.x ONLY (not 3.x/4.x, different API)
 *   "RCSwitch"  by sui77   — any recent version
 *   "HunterFan" — local library (symlinked from arduino/HunterFan)
 *
 * Wiring:
 *   IR LED anode    → 100Ω resistor → Pin 3   (Timer 2, must be Pin 3)
 *   IR LED cathode  → GND
 *   IR receiver     DATA → Pin 11,  VCC → 5V,  GND → GND
 *
 *   RF transmitter  DATA → Pin 10,  VCC → 5V,  GND → GND   (FS1000A / RCSwitch)
 *   RF receiver     DATA → Pin 2,   VCC → 5V,  GND → GND   (XY-MK-5V)
 *     Pin 2 = INT0 — shared between RCSwitch (RFLEARN) and HunterFan (FANLEARN).
 *     Only one listener is active at a time — they take turns.
 *
 *   Hunter fan TX   DATA → Pin 9,   VCC → 5V,  GND → GND   (433 MHz TX module)
 *
 *   Garage remote   Button pin → Pin 4,  remote GND → Arduino GND
 *     Power remote from Arduino 3.3V pin instead of its CR2032.
 *     Remote uses internal pull-down; button press pulls pin HIGH.
 *     Pin 4 idles as INPUT (hi-Z); pulses OUTPUT HIGH for 1s to press button.
 *
 * Serial protocol — 9600 baud, newline-terminated:
 *   PING\n                              → PONG\n
 *   SEND  <PROTO> <HEXCODE> <BITS>\n   → OK\n          (IR send)
 *   LEARN\n                            → CODE <PROTO> <HEXCODE> <BITS>\n  (IR learn)
 *   RFSEND <HEXCODE> <BITS> <PROTO>\n  → OK\n          (RCSwitch RF send)
 *   RFLEARN\n                          → RFCODE <HEXCODE> <BITS> <PROTO>\n (RCSwitch RF learn)
 *   FANSEND <HEX> <BITS>\n             → OK\n          (Hunter fan send)
 *   FANLEARN\n                         → FANCODE <HEX> <BITS>\n  (Hunter fan learn)
 *   GDOOR\n                            → OK\n          (garage door trigger)
 *   Any of the above → TIMEOUT\n or ERROR msg\n on failure
 *
 * Note on timer sharing:
 *   IRremote v2 uses Timer 2 for the IR carrier. RCSwitch receive uses INT0.
 *   They don't share hardware, but we still disable each receiver before
 *   activating the other to keep interrupt load clean.
 */

#include <IRremote.h>
#include <RCSwitch.h>
#include <HunterFan.h>

#define IR_RECV_PIN  11   // Any digital pin except 3
#define RF_SEND_PIN  10   // Any digital pin
#define RF_RECV_PIN   2   // INT0 — shared between RCSwitch and HunterFan RX (mutual exclusion)
#define FAN_SEND_PIN  9   // Hunter fan RF TX module
#define GARAGE_PIN    4   // Garage remote button hi-side; idles hi-Z, pulses LOW to trigger

IRsend   irsend;                 // Send pin hardwired to Pin 3 in IRremote v2
IRrecv   irrecv(IR_RECV_PIN);
decode_results irResults;

RCSwitch rf;
HunterFan fan(FAN_SEND_PIN);     // TX-only; RX enabled on demand via enableReceive()

// ─── Setup ──────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  rf.enableTransmit(RF_SEND_PIN);
  rf.setRepeatTransmit(5);  // send each code 5× for reliability
  fan.begin();               // sets up TX pin; RX attached on demand
  pinMode(GARAGE_PIN, INPUT); // hi-Z until triggered
  // Receivers are enabled only on demand.
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
  if      (cmd == "PING")               Serial.println("PONG");
  else if (cmd == "?")                  Serial.println("UNO_IR");
  else if (cmd.startsWith("SEND "))    doIRSend(cmd);
  else if (cmd == "LEARN")             doIRLearn();
  else if (cmd.startsWith("RFSEND ")) doRFSend(cmd);
  else if (cmd == "RFLEARN")           doRFLearn();
  else if (cmd.startsWith("FANSEND ")) doFanSend(cmd);
  else if (cmd == "FANLEARN")          doFanLearn();
  else if (cmd == "GDOOR")             doGarage();
  else                                  Serial.println("ERROR unknown command");
}

// ─── IR SEND ─────────────────────────────────────────────────────────────────
// SEND <PROTOCOL> <HEXCODE> <BITS>
// e.g. SEND NEC 807F817E 32
void doIRSend(const String& cmd) {
  int p1 = 5;
  int p2 = cmd.indexOf(' ', p1);
  if (p2 < 0) { Serial.println("ERROR malformed"); return; }
  int p3 = cmd.indexOf(' ', p2 + 1);
  if (p3 < 0) { Serial.println("ERROR malformed"); return; }

  String protocol = cmd.substring(p1, p2);
  protocol.toUpperCase();
  unsigned long code = strtoul(cmd.substring(p2 + 1, p3).c_str(), NULL, 16);
  int bits = cmd.substring(p3 + 1).toInt();
  if (bits == 0) bits = 32;

  rf.disableReceive();   // keep interrupt load clean
  irrecv.disableIRIn();

  if      (protocol == "NEC")      irsend.sendNEC(code, bits);
  else if (protocol == "SAMSUNG")  irsend.sendSAMSUNG(code, bits);
  else if (protocol == "SONY") {
    for (int i = 0; i < 3; i++) { irsend.sendSony(code, bits); delay(40); }
  }
  else if (protocol == "RC5")      irsend.sendRC5(code, bits);
  else if (protocol == "RC6")      irsend.sendRC6(code, bits);
  else if (protocol == "LG")       irsend.sendLG(code, bits);
  else if (protocol == "PANASONIC") irsend.sendPanasonic(code >> 16, code & 0xFFFF);
  else if (protocol == "SHARP")    irsend.sendSharp(code >> 8, code & 0xFF);
  else                             irsend.sendNEC(code, bits); // fallback

  Serial.println("OK");
}

// ─── IR LEARN ────────────────────────────────────────────────────────────────
void doIRLearn() {
  rf.disableReceive();
  irrecv.enableIRIn();
  unsigned long deadline = millis() + 10000UL;

  while (millis() < deadline) {
    if (irrecv.decode(&irResults)) {
      unsigned long value = irResults.value;
      irrecv.resume();
      if (value == 0xFFFFFFFFUL || value == 0) continue; // skip repeats
      irrecv.disableIRIn();

      char hexbuf[9];
      sprintf(hexbuf, "%08lX", value);
      Serial.print("CODE ");
      Serial.print(irProtocolName(irResults.decode_type));
      Serial.print(" ");
      Serial.print(hexbuf);
      Serial.print(" ");
      Serial.println(irResults.bits);
      return;
    }
    delay(10);
  }

  irrecv.disableIRIn();
  Serial.println("TIMEOUT");
}

// ─── RF SEND ─────────────────────────────────────────────────────────────────
// RFSEND <HEXCODE> <BITS> <PROTO>
// e.g.   RFSEND 1A2B3C 24 1
void doRFSend(const String& cmd) {
  int p1 = 7;
  int p2 = cmd.indexOf(' ', p1);
  if (p2 < 0) { Serial.println("ERROR malformed"); return; }
  int p3 = cmd.indexOf(' ', p2 + 1);
  if (p3 < 0) { Serial.println("ERROR malformed"); return; }

  unsigned long code = strtoul(cmd.substring(p1, p2).c_str(), NULL, 16);
  int bits     = cmd.substring(p2 + 1, p3).toInt();
  int protocol = cmd.substring(p3 + 1).toInt();
  if (bits == 0)     bits     = 24;
  if (protocol == 0) protocol = 1;

  rf.disableReceive();
  irrecv.disableIRIn();

  rf.setProtocol(protocol);
  rf.send(code, bits);

  Serial.println("OK");
}

// ─── RF LEARN ────────────────────────────────────────────────────────────────
void doRFLearn() {
  irrecv.disableIRIn();
  rf.enableReceive(RF_RECV_PIN - 2);  // RCSwitch takes interrupt number: pin2=0, pin3=1
  unsigned long deadline = millis() + 10000UL;

  while (millis() < deadline) {
    if (rf.available()) {
      unsigned long value    = rf.getReceivedValue();
      int           bits     = rf.getReceivedBitlength();
      int           protocol = rf.getReceivedProtocol();
      rf.resetAvailable();
      rf.disableReceive();

      if (value == 0) {
        Serial.println("TIMEOUT"); // unrecognised signal
        return;
      }

      char hexbuf[9];
      sprintf(hexbuf, "%06lX", value);
      Serial.print("RFCODE ");
      Serial.print(hexbuf);
      Serial.print(" ");
      Serial.print(bits);
      Serial.print(" ");
      Serial.println(protocol);
      return;
    }
    delay(10);
  }

  rf.disableReceive();
  Serial.println("TIMEOUT");
}

// ─── HUNTER FAN SEND ─────────────────────────────────────────────────────────
// FANSEND <HEX> <BITS>
// e.g.   FANSEND A6FF346CBB18067F80 66
void doFanSend(const String& cmd) {
  int p1 = 8;
  int p2 = cmd.indexOf(' ', p1);
  if (p2 < 0) { Serial.println("ERROR malformed"); return; }

  String hex  = cmd.substring(p1, p2);
  uint8_t bits = (uint8_t)cmd.substring(p2 + 1).toInt();
  if (bits == 0) bits = 66;

  rf.disableReceive();
  irrecv.disableIRIn();

  fan.sendHex(hex.c_str(), bits);
  Serial.println("OK");
}

// ─── HUNTER FAN LEARN ────────────────────────────────────────────────────────
// Pin 2 (INT0) is shared with RCSwitch. Enable HunterFan ISR, receive, detach.
void doFanLearn() {
  rf.disableReceive();
  irrecv.disableIRIn();

  fan.enableReceive(RF_RECV_PIN);

  uint8_t data[16];
  uint8_t bits = 0;
  bool got = fan.receive(data, sizeof(data), bits, 12000);

  fan.disableReceive();

  if (!got) { Serial.println("TIMEOUT"); return; }

  Serial.print("FANCODE ");
  Serial.print(HunterFan::toHex(data, (bits + 7) / 8));
  Serial.print(" ");
  Serial.println(bits);
}

// ─── GARAGE DOOR ─────────────────────────────────────────────────────────────
void doGarage() {
  pinMode(GARAGE_PIN, OUTPUT);
  digitalWrite(GARAGE_PIN, HIGH);
  delay(1000);
  pinMode(GARAGE_PIN, INPUT); // back to hi-Z
  Serial.println("OK");
}

// ─── IR protocol name ────────────────────────────────────────────────────────
const char* irProtocolName(int type) {
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
