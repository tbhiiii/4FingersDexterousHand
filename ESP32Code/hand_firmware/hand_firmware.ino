// AmazingHand PWM firmware: protocol v1 (docs/protocol.md) over USB serial and UDP.
// The PC computes; this sketch parses lines, clamps angles, drives the servos and runs the grip current loop.
#include <WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <Adafruit_INA219.h>

#include "secrets.h"            // copy secrets.example.h to secrets.h (gitignored)
#include "protocol.h"
#include "protocol_selftest.h"  // compile-time parser tests, no runtime cost

// Declared before any function: the Arduino builder inserts prototypes above the first function definition.
enum class Src { Serial, Udp };

constexpr uint32_t kBaud = 115200;
constexpr uint16_t kUdpPort = 6000;
constexpr uint32_t kGripTickMs = 20;
constexpr uint32_t kWatchdogMs = 2000;
constexpr int N = proto::kServoCount;

// Servo index i is plugged into PCA9685 channel i (docs/hardware.md#servo-map).
// Finger f = servo f (side A) + servo f+4 (side B).
constexpr uint8_t kPcaAddr = 0x40;
constexpr uint32_t kI2cHz = 400000;
// shortcut: datasheet says 25 MHz but chips vary 23-27 MHz; if servo end points are off, measure and set this.
constexpr uint32_t kPcaOscHz = 25000000;
constexpr int kServoHz = 50;
constexpr int kMinUs = 544;   // same pulse range the ESP32Servo version used
constexpr int kMaxUs = 2400;

// Angle (0-180) -> PCA9685 on-time in ticks of a 4096-tick, 20 ms frame.
constexpr int angleToTicks(int deg) {
  int us = kMinUs + (deg * (kMaxUs - kMinUs) + 90) / 180;
  return (us * 4096 * kServoHz + 500000) / 1000000;
}
static_assert(angleToTicks(0) == 111 && angleToTicks(90) == 301 && angleToTicks(180) == 492, "pulse mapping");

constexpr int kHome[N] = {20, 20, 20, 20, 160, 160, 160, 160};
// shortcut: full 0-180 range until each servo is measured; fill docs/hardware.md calibration, then narrow these.
constexpr int kMin[N] = {0, 0, 0, 0, 0, 0, 0, 0};
constexpr int kMax[N] = {180, 180, 180, 180, 180, 180, 180, 180};
// +1: closing moves servo f up and servo f+4 down. Keep equal to FLEX_SIGN in AmazingHand_GUIDesign/hand_model.py.
constexpr int kFlexSign[proto::kFingerCount] = {1, 1, 1, 1};

// The INA219 sits on the second I2C bus (Wire1), so it keeps its default 0x40 without clashing with the
// PCA9685 on Wire, and no address pad needs soldering. SDA 18 / SCL 19 are free, non-strapping pins.
constexpr int kInaSda = 18;
constexpr int kInaScl = 19;
// shortcut: one INA219; add one entry per extra sensor at a free address on Wire1 (0x41, 0x44, 0x45).
Adafruit_INA219 ina[] = {Adafruit_INA219(0x40)};
constexpr int kInaCount = sizeof(ina) / sizeof(ina[0]);
bool inaOk[kInaCount];

Adafruit_PWMServoDriver pca(kPcaAddr);
bool pcaOk = false;
int angle[N];
WiFiUDP udp;
bool udpStarted = false;
proto::LineReader serialReader;
proto::LineReader udpReader;

proto::Command grip;
bool gripActive = false;
Src gripSrc = Src::Serial;
IPAddress gripIp;
uint16_t gripPort = 0;
uint32_t lastGripTickMs = 0;
uint32_t lastLineMs = 0;

void sendTo(Src src, IPAddress ip, uint16_t port, const char* text) {
  if (src == Src::Serial) {
    Serial.println(text);
    return;
  }
  udp.beginPacket(ip, port);
  udp.print(text);
  udp.print('\n');
  udp.endPacket();
}

// Reply to the sender of the line being handled.
void reply(Src src, const char* text) { sendTo(src, udp.remoteIP(), udp.remotePort(), text); }

void writeAngles(const int* target) {
  for (int i = 0; i < N; ++i) {
    angle[i] = proto::clamp(target[i], kMin[i], kMax[i]);  // trust boundary: never skip
    pca.setPWM(i, 0, angleToTicks(angle[i]));
  }
}

// Channel fully off: no pulses, the servos go limp.
void detachAll() {
  for (int i = 0; i < N; ++i) pca.setPWM(i, 0, 4096);
}

bool anySensor() {
  for (int i = 0; i < kInaCount; ++i) {
    if (inaOk[i]) return true;
  }
  return false;
}

// Sum of |current| over the sensors that answered at boot; -1 if any of them fails now.
int totalCurrentMa() {
  float sum = 0;
  for (int i = 0; i < kInaCount; ++i) {
    if (!inaOk[i]) continue;
    float ma = ina[i].getCurrent_mA();
    if (!ina[i].success()) return -1;  // success() reports the last I2C transfer (the current read)
    sum += fabsf(ma);
  }
  return static_cast<int>(sum);
}

void endGrip(const char* reason) {
  gripActive = false;
  char out[32];
  snprintf(out, sizeof out, "GRIP:DONE %s", reason);
  sendTo(gripSrc, gripIp, gripPort, out);
}

void handle(Src src, const proto::Command& c) {
  char out[proto::kMaxLine + 32];
  if (c.type != proto::Type::None && c.type != proto::Type::Error) lastLineMs = millis();
  switch (c.type) {
    case proto::Type::None:
      return;
    case proto::Type::Angles:
      gripActive = false;
      writeAngles(c.angles);  // streamed: no reply
      return;
    case proto::Type::Home:
      gripActive = false;
      writeAngles(kHome);
      reply(src, "OK");
      return;
    case proto::Type::Stop:
      gripActive = false;
      detachAll();
      reply(src, "OK");
      return;
    case proto::Type::Ping:
      reply(src, "PONG v1");
      return;
    case proto::Type::Status: {
      int n = snprintf(out, sizeof out, "ST:");
      for (int i = 0; i < N; ++i) n += snprintf(out + n, sizeof out - n, i ? ",%d" : "%d", angle[i]);
      n += snprintf(out + n, sizeof out - n, ";I:");
      for (int i = 0; i < kInaCount; ++i) {
        const char* sep = i ? "," : "";
        if (inaOk[i]) n += snprintf(out + n, sizeof out - n, "%s%d", sep, static_cast<int>(ina[i].getCurrent_mA()));
        else n += snprintf(out + n, sizeof out - n, "%sNA", sep);
      }
      reply(src, out);
      return;
    }
    case proto::Type::Grip:
      if (!anySensor()) {
        reply(src, "ERR:NOSENSOR");  // never squeeze without force sensing
        return;
      }
      writeAngles(angle);  // restart pulses if STOP turned the channels off
      grip = c;
      gripActive = true;
      gripSrc = src;
      gripIp = udp.remoteIP();
      gripPort = udp.remotePort();
      lastGripTickMs = millis();
      return;
    case proto::Type::Error:
      snprintf(out, sizeof out, "ERR:%s", proto::errName(c.err));
      reply(src, out);
      return;
  }
}

void dispatch(Src src, const proto::LineReader& r) {
  if (r.overflowed()) reply(src, "ERR:PARSE");
  else handle(src, proto::parse(r.line()));
}

void runGrip() {
  if (!gripActive) return;
  uint32_t now = millis();
  if (now - lastLineMs > kWatchdogMs) {
    endGrip("WATCHDOG");  // PC went quiet: stop closing, hold position
    return;
  }
  if (now - lastGripTickMs < kGripTickMs) return;
  lastGripTickMs = now;
  int next[N];
  for (int i = 0; i < N; ++i) next[i] = angle[i];
  proto::GripResult r = proto::gripTick(grip, next, totalCurrentMa(), kMin, kMax, kFlexSign);
  writeAngles(next);
  if (r == proto::GripResult::Current) endGrip("CURRENT");
  else if (r == proto::GripResult::Limit) endGrip("LIMIT");
  else if (r == proto::GripResult::Sensor) endGrip("SENSOR");
}

void setup() {
  Serial.begin(kBaud);
  Wire.begin();
  pcaOk = pca.begin();
  if (pcaOk) {
    pca.setOscillatorFrequency(kPcaOscHz);
    pca.setPWMFreq(kServoHz);
    delay(10);  // let the new prescale take effect before the first pulse
    writeAngles(kHome);
  } else {
    Serial.println("INFO:NOPCA9685");  // nothing can move; PING/STATUS still work
  }
  Wire.setClock(kI2cHz);
  Wire1.begin(kInaSda, kInaScl, kI2cHz);
  for (int i = 0; i < kInaCount; ++i) inaOk[i] = ina[i].begin(&Wire1);
  if (WIFI_SSID[0] != '\0') {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);  // non-blocking: serial works while WiFi connects
  }
}

void loop() {
  while (Serial.available() > 0) {
    if (serialReader.push(static_cast<char>(Serial.read()))) dispatch(Src::Serial, serialReader);
  }

  if (!udpStarted && WiFi.status() == WL_CONNECTED) {
    udpStarted = udp.begin(kUdpPort);
    Serial.print("INFO:IP ");
    Serial.println(WiFi.localIP());
  }
  if (udpStarted && udp.parsePacket() > 0) {
    while (udp.available() > 0) {
      if (udpReader.push(static_cast<char>(udp.read()))) dispatch(Src::Udp, udpReader);
    }
    if (udpReader.push('\n')) dispatch(Src::Udp, udpReader);  // packet end also ends a line; an extra empty line is ignored
  }

  runGrip();
}
