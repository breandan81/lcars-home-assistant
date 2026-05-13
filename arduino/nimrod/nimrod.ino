#include <ESP8266WiFi.h>

#define RX_PIN      D2
#define TX_PIN      D1

volatile bool newPulse = false;
volatile unsigned long timeStamp = 0;

void ICACHE_RAM_ATTR onPulse();

const long packetSize = 32; // bytes per packet (adjust as needed)
const long rawTimesSize = packetSize * 8 * 3; // max bits * max transitions per bit

const long minClkPeriodUs = 380;
const long maxClkPeriodUs = 420;
const long clkPeriod = 400; // nominal clock period in microseconds (adjust as needed)

const long minAnchorPeriodUs = minClkPeriodUs * 13;
const long maxAnchorPeriodUs = maxClkPeriodUs * 13;

const long minSetBitPeriodUs = minClkPeriodUs * 2;
const long maxSetBitPeriodUs = maxClkPeriodUs * 2;

const long minClearBitPeriodUs = minClkPeriodUs * 1;
const long maxClearBitPeriodUs = maxClkPeriodUs * 1;

const long minSyncPulses = 16; // minimum consecutive 1 clock transitions to consider valid sync
const long packetBufCount = 5; // how many packets to store/read (adjust as needed)

uint8_t bytes[packetBufCount][packetSize]; // store up to 5 packets of 16 bytes each (adjust as needed)
uint8_t txBytes[packetSize]; // buffer for sending packets

uint16_t rawTimes[rawTimesSize]; // store raw timings for debugging (max bits * 3 transitions per bit)
uint16_t timesCaptured = 0;

int bitCount = 0;

bool readLineFromSerial(char *out, size_t outSize, unsigned long timeoutMs);


enum FailureCause {
  NO_FAILURE = 0,
  NO_ANCHOR = 1,
  INVALID_PULSE = 2,
  NO_SYNC = 3,
  NO_EOP = 4
};

FailureCause failureCause = NO_FAILURE;

long readIntFromSerial(unsigned long timeoutMs = 0)
{
    char buf[12]; // enough for -2147483648 + null
    if (!readLineFromSerial(buf, sizeof(buf), timeoutMs))
    {
        return 0;
    }
    return atol(buf);
}

void printFailureCause() {
  switch (failureCause) {
    case NO_FAILURE:
      Serial.println("No failure");
      break;
    case NO_ANCHOR:
      Serial.println("Failure: No anchor pulse detected");
      break;
    case INVALID_PULSE:
      Serial.println("Failure: Invalid pulse timing detected");
      break;
    case NO_SYNC:
      Serial.println("Failure: No sync detected");
      break;
    case NO_EOP:
      Serial.println("Failure: No end of packet detected (timings overflow)");
      break;
    default:
      Serial.println("Failure: Unknown cause");
      break;
  }
}

bool isOneClock(long periodUs)
{
  return (periodUs >= minClkPeriodUs && periodUs <= maxClkPeriodUs);
}
bool isAnchor(long periodUs)
{
  return (periodUs >= minAnchorPeriodUs && periodUs <= maxAnchorPeriodUs);
}
bool isSetBit(long periodUs)
{
  return (periodUs >= minSetBitPeriodUs && periodUs <= maxSetBitPeriodUs);
}
bool isClearBit(long periodUs)
{
  return (periodUs >= minClearBitPeriodUs && periodUs <= maxClearBitPeriodUs);
}

bool getBit(uint8_t *byteArr, long bitIdx)
{
  long byteIdx = bitIdx / 8;
  int bitInByte = bitIdx % 8;
  if (byteIdx >= packetSize) return false; // out of bounds
  return (byteArr[byteIdx] >> bitInByte) & 0x01;
}

void setBit(uint8_t *byteArr, long bitIdx, bool value)
{
  long byteIdx = bitIdx / 8;
  int bitInByte = bitIdx % 8;
  if (byteIdx >= packetSize) return; // out of bounds
  if (value)
  {
    byteArr[byteIdx] |= (1 << bitInByte);
  }
  else
  {
    byteArr[byteIdx] &= ~(1 << bitInByte);
  }
}

uint8_t reverseBits(uint8_t b)
{
  b = (b & 0xF0) >> 4 | (b & 0x0F) << 4;
  b = (b & 0xCC) >> 2 | (b & 0x33) << 2;
  b = (b & 0xAA) >> 1 | (b & 0x55) << 1;
  return b;
}

char *packetToHexString(const uint8_t *byteArr, size_t byteCount)
{
  static char hexStr[33];  // 16 bytes -> 32 hex chars + NUL
  size_t pos = 0;

  if (byteCount > packetSize)
  {
    byteCount = packetSize;
  }

  for (size_t i = 0; i < byteCount; i++)
  {
    uint8_t reversed = reverseBits(byteArr[i]);
    snprintf(hexStr + pos, sizeof(hexStr) - pos, "%02X", reversed);
    pos += 2;
  }

  hexStr[pos] = '\0';
  return hexStr;
}

int hexNibble(char c);

bool loadHexStringToPacket(const char *hexStr, uint8_t *byteArr, size_t maxBytes)
{
  if (hexStr == nullptr || byteArr == nullptr)
  {
    return false;
  }

  size_t hexLen = strlen(hexStr);

  if ((hexLen % 2) != 0)
  {
    return false;
  }

  size_t byteCount = hexLen / 2;

  if (byteCount > maxBytes)
  {
    byteCount = maxBytes;
  }

  for (size_t i = 0; i < byteCount; i++)
  {
    int highVal = hexNibble(hexStr[i * 2]);
    int lowVal = hexNibble(hexStr[i * 2 + 1]);

    if (highVal < 0 || lowVal < 0)
    {
      return false;
    }

    byteArr[i] = reverseBits((uint8_t)((highVal << 4) | lowVal));
  }
  return true;
}
bool readLineFromSerial(char *out, size_t outSize, unsigned long timeoutMs = 0)
{
  if (outSize == 0) return false;

  size_t idx = 0;
  unsigned long start = millis();
  bool waitForever = (timeoutMs == 0);

  while (waitForever || (millis() - start < timeoutMs))
  {
    while (Serial.available() > 0)
    {
      int v = Serial.read();
      if (v < 0) continue;
      char c = (char)v;

      if (c == '\r') continue;      // ignore CR
      if (c == '\n')               // line complete
      {
        out[idx] = '\0';
        return idx > 0;
      }

      if (idx < outSize - 1)
      {
        out[idx++] = c;             // keep room for '\0'
      }
    }
  }

  if (waitForever)
  {
    out[idx] = '\0';
    return idx > 0;
  }

  out[idx] = '\0';                  // timeout: return partial/empty
  return idx > 0;
}

int hexNibble(char c)
{
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
  if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
  return -1;
}

// Reads hex bytes from Serial into out[] until newline or timeout.
// Accepts formats like: A6FF34, A6 FF 34, 0xA6,0xFF,0x34
// - maxBytes: maximum bytes to store in out[]
// - timeoutMs: max time to wait for newline/data
// Returns number of bytes written to out[].
// Discards any extra data (past maxBytes) until '\n'.
size_t readHexFromSerial(uint8_t *out, size_t maxBytes, unsigned long timeoutMs = 0) 
{
  if (out == nullptr || maxBytes == 0) {
    // Still flush to newline so caller starts clean next time
    unsigned long t0 = millis();
    while (millis() - t0 < timeoutMs) {
      while (Serial.available() > 0) {
        char c = (char)Serial.read();
        if (c == '\n') return 0;
      }
    }
    return 0;
  }


  size_t count = 0;
  int high = -1;              // pending high nibble
  bool lineDone = false;
  unsigned long start = millis();
  bool waitForever = (timeoutMs == 0);

  while (!lineDone && (waitForever || (millis() - start < timeoutMs))) {
    while (Serial.available() > 0) {
      char c = (char)Serial.read();

      if (c == '\r') continue;
      if (c == '\n') { lineDone = true; break; }

      // Ignore separators
      if (c == ' ' || c == '\t' || c == ',' || c == ';' || c == ':') continue;

      // Ignore optional 0x/0X prefix
      if (c == 'x' || c == 'X') {
        if (high == 0) { high = -1; } // consumed a leading '0' before x
        continue;
      }

      int n = hexNibble(c);
      if (n < 0) continue; // ignore any non-hex junk

      if (high < 0) {
        high = n;
      } else {
        uint8_t byteVal = (uint8_t)((high << 4) | n);
        high = -1;
        if (count < maxBytes) {
          out[count++] = byteVal;
        }
        // else: overflow bytes are intentionally discarded
      }
    }
  }

  // If maxBytes was reached, discard the rest of the line.
  if (!lineDone) {
    // timed out without newline; leave as-is
    return count;
  }

  // If we ended with odd hex digit, it's ignored (no low nibble).
  return count;
}

void setup()
{
  Serial.begin(115200);
  pinMode(RX_PIN, INPUT);
  pinMode(TX_PIN, OUTPUT);
  attachInterrupt(digitalPinToInterrupt(RX_PIN), onPulse, CHANGE);
}



void ICACHE_RAM_ATTR onPulse()
{
  newPulse = true;
  timeStamp = micros();
}

void zeroRawTimes() {
  for (size_t i = 0; i < rawTimesSize; i++) {
    rawTimes[i] = 0;
  }
  timesCaptured = 0;
}
bool hunterReadTimes()
{
/* simple state machine
    first state idle/waiting for sync packet which is at least minSyncPulses transitions 1 clock cycle apart
    second state: wait for anchor pulse - transition 13 clock cycles after last sync pulse 
    third state: long transitions are set bits, short transitions are clear bits, read until we get a long transition that is at least 15 cycles after the last sync pulse (indicating end of packet and start of next sync)
    */

    bitCount = 0;
    long lastTransitionTime = 0;
    int syncPulses = 0;
    newPulse = false;
    failureCause = NO_FAILURE;

    unsigned long absoluteTimeOutMs = 2000; // 2 second timeout for entire read operation
    unsigned long startTime = millis();
    ESP.wdtDisable();

    zeroRawTimes();

    //wait for sync burst
    while (true) 
    {
        if(millis() - startTime > absoluteTimeOutMs) {
            // timeout waiting for sync
        //   ESP.wdtEnable(0);
            return false;
        }
        if (newPulse)
        {
            newPulse = false;
            unsigned long now = timeStamp;
            unsigned long period = now - lastTransitionTime;
            lastTransitionTime = now;


            if(isOneClock(period))
            {
                syncPulses++;
            }
            else
            {
                syncPulses = 0;
            }
            if (syncPulses >= minSyncPulses)
            {
                break; // sync acquired
            }
        }
          else
          {
          }
    }
    //wait for anchor pulse
    while (true) 
    {
        if(millis() - startTime > absoluteTimeOutMs) 
        {
            // timeout 
            // ESP.wdtEnable(0);
            return false;
        }
        if (newPulse)
        {
            newPulse = false;
            unsigned long now = timeStamp;
            unsigned long period = now - lastTransitionTime;
            lastTransitionTime = now;

            if(isAnchor(period))
            {
                break; // anchor acquired
            }
            else if(!isOneClock(period))
            {
                // if we get a non-clock, non-anchor pulse, it means sync was lost and we give up
                //reset everything
                bitCount = 0;
                failureCause = NO_ANCHOR;
                // ESP.wdtEnable(0);
                return false;
            }
        }
        else
        {
        }
    }
    //read bits until we get a long pulse that is at least 15 cycles after the last sync pulse (indicating end of packet and start of next sync)
    while (true)    
    {
    // long pulse or short pulse for 1 or 0, then wait for next pulse
        bool isLongPulse = false;
        if( (millis() - startTime > absoluteTimeOutMs))
        {
            // timeout waiting for sync
            // ESP.wdtEnable(0);
            Serial.println("Timeout waiting for pulse");
            return false;
        }
        if (newPulse)
        {
           newPulse = false;
            unsigned long now = timeStamp;
            unsigned long period = now - lastTransitionTime;
            lastTransitionTime = now;

            if(isSetBit(period))
            {
                isLongPulse = true;
            }
            else if(isClearBit(period))
            {
                isLongPulse = false;
            }

            rawTimes[timesCaptured++] = (uint16_t)period;

            while(true) 
            {
                if( (millis() - startTime > absoluteTimeOutMs))
                {   
                // timeout waiting for sync
                // ESP.wdtEnable(0);
                Serial.println("Timeout waiting for pulse");
                return false;
                }
                if(timesCaptured >= rawTimesSize) 
                {
                    // we've captured as many timings as we can store, so we stop here
                    failureCause = NO_EOP;
                    // ESP.wdtEnable(0);
                    return true;
                }
                if (newPulse)
                {
                    newPulse = false;
                    now = timeStamp;
                    period = now - lastTransitionTime;
                    lastTransitionTime = now;
                    rawTimes[timesCaptured++] = (uint16_t)period;

                    if(isLongPulse && !isOneClock(period))
                    {
                        // this isn't expected so we reset and fail
                        failureCause = INVALID_PULSE;
                    }
                    else if(!isLongPulse && !isSetBit(period))
                    {
                        // this isn't expected so we reset and fail
                        failureCause = INVALID_PULSE;
                    }
                    else if(!isSetBit(period) && !isOneClock(period))
                    {
                        failureCause = INVALID_PULSE;
                    }
                    else
                    {
                        break; // valid pulse, continue reading
                    }
                    
                }
                if((micros() - lastTransitionTime) > minAnchorPeriodUs)
                {
                        // successful end  of packet
                        failureCause = NO_FAILURE  ;
                        // ESP.wdtEnable(0);
                        return true;
                }
            }
        }
    }
    // ESP.wdtEnable(0);
    return true;
}

bool hunterRead(uint8_t *outBytes, size_t maxBytes)
{
/* simple state machine
    first state idle/waiting for sync packet which is at least minSyncPulses transitions 1 clock cycle apart
    second state: wait for anchor pulse - transition 13 clock cycles after last sync pulse 
    third state: long transitions are set bits, short transitions are clear bits, read until we get a long transition that is at least 15 cycles after the last sync pulse (indicating end of packet and start of next sync)
    */

    bitCount = 0;
    long maxBitCount = maxBytes * 8;
    long lastTransitionTime = 0;
    int syncPulses = 0;
    newPulse = false;
    failureCause = NO_FAILURE;

    unsigned long absoluteTimeOutMs = 2000; // 2 second timeout for entire read operation
    unsigned long startTime = millis();
    ESP.wdtDisable();

    //wait for sync burst
    while (true) 
    {
        if(millis() - startTime > absoluteTimeOutMs) {
            // timeout waiting for sync
            // ESP.wdtEnable(0);
            failureCause = NO_SYNC;
            return false;
        }
        if (newPulse)
        {
            newPulse = false;
            unsigned long now = timeStamp;
            unsigned long period = now - lastTransitionTime;
            lastTransitionTime = now;


            if(isOneClock(period))
            {
                syncPulses++;
            }
            else
            {
                syncPulses = 0;
            }
            if (syncPulses >= minSyncPulses)
            {
                break; // sync acquired
            }
        }
        else
          {
          }
    }
    //wait for anchor pulse
    while (true) 
    {
        if(millis() - startTime > absoluteTimeOutMs) 
        {
            // timeout 
            // ESP.wdtEnable(0);
            return false;
        }
        if (newPulse)
        {
            newPulse = false;
            unsigned long now = timeStamp;
            unsigned long period = now - lastTransitionTime;
            lastTransitionTime = now;

            if(isAnchor(period))
            {
                break; // anchor acquired
            }
            else if(!isOneClock(period))
            {
                // if we get a non-clock, non-anchor pulse, it means sync was lost and we give up
                //reset everything
                bitCount = 0;
                failureCause = NO_ANCHOR;
                // ESP.wdtEnable(0);
                return false;
            }
            else
            {
            }
        }
    }
    //read bits until we get a long pulse that is at least 15 cycles after the last sync pulse (indicating end of packet and start of next sync)
    while (true)    
    {
    // long pulse or short pulse for 1 or 0, then wait for next pulse
        bool isLongPulse = false;
        if(millis() - startTime > absoluteTimeOutMs) 
        {
            // timeout waiting for sync
          // ESP.wdtEnable(0);
            return false;
        }
        if (newPulse)
        {
            newPulse = false;
            unsigned long now = timeStamp;
            unsigned long period = now - lastTransitionTime;
            lastTransitionTime = now;

            if(isSetBit(period))
            {
              if (bitCount >= maxBitCount)
              {
                // ESP.wdtEnable(0);
                return true;
              }
                setBit(outBytes, bitCount, true);
                isLongPulse = true;
                bitCount++;
            }
            else if(isClearBit(period))
            {
              if (bitCount >= maxBitCount)
              {
                // ESP.wdtEnable(0);
                return true;
              }
                setBit(outBytes, bitCount, false);
                isLongPulse = false;
                bitCount++;
            }
            else
            {
                // invalid pulse timing, we fail
                failureCause = INVALID_PULSE;
                // ESP.wdtEnable(0);
                return false;
            }

            while(true) 
            {
                if( (millis() - startTime > absoluteTimeOutMs))
                {   
                // timeout waiting for sync
                // ESP.wdtEnable(0);
                Serial.println("Timeout waiting for pulse");
                return false;
                }
                if (newPulse)
                {
                    newPulse = false;
                    now = timeStamp;
                    period = now - lastTransitionTime;
                    lastTransitionTime = now;

                    if(isLongPulse && !isOneClock(period))
                    {
                        // this isn't expected so we reset and fail
                        failureCause = INVALID_PULSE;
                        // ESP.wdtEnable(0);
                        return false;
                    }
                    else if(!isLongPulse && !isSetBit(period))
                    {
                        // this isn't expected so we reset and fail
                        failureCause = INVALID_PULSE;
                        // ESP.wdtEnable(0);
                        return false;
                    }
                    else if(!isSetBit(period) && !isOneClock(period))
                    {
                        failureCause = INVALID_PULSE;
                        // ESP.wdtEnable(0);
                        return false;
                    }
                    else
                    {
                        break; // valid pulse, continue reading
                    }   
                }
                if((micros() - lastTransitionTime) > minAnchorPeriodUs)
                {
                        // successful end  of packet
                        failureCause = NO_FAILURE  ;
                        // ESP.wdtEnable(0);
                        return true;
                }
            }
        }
    }
    // ESP.wdtEnable(0);
    return true;
}

void waitForNextRFClock()
{
    unsigned long startTime = micros()%clkPeriod;
    while ((micros() % clkPeriod) > startTime) 
    {
        startTime = micros()%clkPeriod;
    }
}

void sendPreamble()
{
    // send 20 clock pulses as preamble
    for (int i = 0; i < 11; i++)
    {
        waitForNextRFClock();
        digitalWrite(TX_PIN, HIGH);
        waitForNextRFClock();
        digitalWrite(TX_PIN, LOW);
    }
}
void sendAnchorPulse()
{
    // send a long pulse for anchor
    digitalWrite(TX_PIN, LOW);
    for(int i = 0; i < 12; i++)
    {
        waitForNextRFClock();
    }
}
void sendLongPulse()
{
    waitForNextRFClock();
    digitalWrite(TX_PIN, HIGH);
    waitForNextRFClock();
    waitForNextRFClock();

    digitalWrite(TX_PIN, LOW);
}
void sendShortPulse()
{
    waitForNextRFClock();
    digitalWrite(TX_PIN, HIGH);
    waitForNextRFClock();
    digitalWrite(TX_PIN, LOW);
}

void sendBuffer(long bits)
{
    sendPreamble();
    sendAnchorPulse();
    for (long i = 0; i < bits; i++)
    {
        bool bitVal = getBit(txBytes, i);
        if (bitVal)
        {
            sendLongPulse();
        }
        else
        {
            sendShortPulse();
        }
    }
}

void hunterPlay()
{
    ESP.wdtDisable();
    memset(txBytes, 0, sizeof(txBytes));
    uint8_t hexBuf[packetSize] = {0xA6, 0xFF, 0x34, 0x6C, 0xBB, 0x18, 0x06, 0x7F, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    //memset(hexBuf, 0, sizeof(hexBuf));
    //size_t bytesRead = readHexFromSerial(hexBuf, packetSize);
    size_t bytesRead = 16;
    // A6FF346CBB18067F8000000000000000
     

    bool bufReceived = (bytesRead > 0);

    Serial.print("bytesRead: ");
    Serial.println(bytesRead);
    //long bitsToSend = readIntFromSerial();

    long bitsToSend=66;

    if (!bufReceived || bitsToSend <= 0)
    {
        Serial.println("Failed to read valid hex string or bit count from serial");
        return;
    }

    char hexStr[packetSize * 2 + 1] = {0};
    for (size_t i = 0; i < packetSize; i++)
    {
        snprintf(hexStr + i * 2, 3, "%02X", hexBuf[i]);
    }

    loadHexStringToPacket(hexStr, txBytes, packetSize);
    Serial.print("sending packet: ");
    Serial.println(packetToHexString(txBytes, bytesRead));
    Serial.print("first 4 bits in binary: ");
    for (int i = 0; i < 4; i++)
    {
        Serial.print(getBit(txBytes, i) ? '1' : '0');
    }
    Serial.println();



    for (int i = 0; i < 3; i++)
    {
        sendBuffer(bitsToSend);
        delayMicroseconds(26000);
    }
}



void loop()
{
    // read serial command "R" for "Read", "P" for "Play"

    int retries = 1;

    bool readSuccess[packetBufCount] = {false};
    if (Serial.available() > 0)
    {
        char command = Serial.read();
        if (command == 'R')
        {
            Serial.println("Read command received, starting RF read...");
              for(int i = 0; i < retries; i++)
              {
                readSuccess[i] = hunterRead(bytes[i], packetSize);
              }
              for(int i = 0; i < retries; i++)
              {
              if (readSuccess[i])
              {
                        Serial.print("Read packet: ");
                        Serial.println(packetToHexString(bytes[i], 128));
                        Serial.println(bitCount);
              }
              else
              {
                        // Serial.print("Failed to read packet: ");
                        // Serial.println(i);
              }
              }
            
        }
        else if (command == 'P')
        {
                // Play mode: read timings from serial and generate pulses
                hunterPlay();
        }
        else if (command == 'D')
        {
            // Dump raw timings for debugging
            hunterReadTimes(); // read timings without decoding
            printFailureCause();
            Serial.println("Raw timings (us):");
            for (size_t i = 0; i < timesCaptured; i++)
            {
                Serial.print(rawTimes[i]);
                Serial.print(i < timesCaptured - 1 ? ", " : "\n");
            }
        }
    }   
    else
    {
        ESP.wdtEnable(2000); // re-enable watchdog with 2 second timeout to prevent lockup when idle
        yield();
    }
}
