// Compile-time tests for protocol.h. A failing case stops the arduino-cli compile.
#pragma once
#include "protocol.h"

namespace proto::selftest {

constexpr bool anglesParsed() {
  Command c = parse("A:20,21,22,23,160,161,162,180");
  return c.type == Type::Angles && c.angles[0] == 20 && c.angles[3] == 23 && c.angles[7] == 180;
}
static_assert(anglesParsed());
static_assert(parse("A:0,0,0,0,0,0,0,0").type == Type::Angles);

static_assert(parse("").type == Type::None);
static_assert(parse("HOME").type == Type::Home);
static_assert(parse("STOP").type == Type::Stop);
static_assert(parse("PING").type == Type::Ping);
static_assert(parse("STATUS").type == Type::Status);

static_assert(parse("A:1,2,3").err == Err::Parse);                 // too few
static_assert(parse("A:1,2,3,4,5,6,7,8,9").err == Err::Parse);     // too many
static_assert(parse("A:1,2,3,4,5,6,7,").err == Err::Parse);        // empty field
static_assert(parse("A:-1,2,3,4,5,6,7,8").err == Err::Parse);      // negative
static_assert(parse("A:1,2,3,4,5,6,7,8 ").err == Err::Parse);      // trailing junk
static_assert(parse("A:1, 2,3,4,5,6,7,8").err == Err::Parse);      // space
static_assert(parse("A:1000,2,3,4,5,6,7,8").err == Err::Parse);    // 4 digits
static_assert(parse("A:1,2,3,4,5,6,7,181").err == Err::Range);
static_assert(parse("ping").err == Err::Unknown);                  // case-sensitive
static_assert(parse("PINGX").err == Err::Unknown);

constexpr bool gripParsed() {
  Command c = parse("GRIP:F,600,2");
  return c.type == Type::Grip && c.mask == 0xF && c.limitMa == 600 && c.step == 2;
}
static_assert(gripParsed());
static_assert(parse("GRIP:3,5000,20").type == Type::Grip);
static_assert(parse("GRIP:0,600,2").err == Err::Range);            // no finger
static_assert(parse("GRIP:F,0,2").err == Err::Range);
static_assert(parse("GRIP:F,5001,2").err == Err::Range);
static_assert(parse("GRIP:F,600,21").err == Err::Range);
static_assert(parse("GRIP:f,600,2").err == Err::Parse);            // lowercase hex
static_assert(parse("GRIP:F,600").err == Err::Parse);
static_assert(parse("GRIP:F,600,2,1").err == Err::Parse);
static_assert(parse("GRIP:FF,600,2").err == Err::Parse);

static_assert(clamp(200, 0, 180) == 180);
static_assert(clamp(-5, 10, 170) == 10);
static_assert(clamp(90, 10, 170) == 90);

constexpr bool readerSplitsLines() {
  LineReader r;
  const char* in = "PI\r\nNG\n";
  int lines = 0;
  bool ok = true;
  for (const char* p = in; *p; ++p) {
    if (r.push(*p)) {
      ++lines;
      ok = ok && !r.overflowed() && equals(r.line(), lines == 1 ? "PI" : "NG");
    }
  }
  return ok && lines == 2;
}
static_assert(readerSplitsLines());

constexpr bool readerRecoversFromOverflow() {
  LineReader r;
  for (int i = 0; i < kMaxLine + 10; ++i) r.push('x');
  if (!r.push('\n') || !r.overflowed()) return false;
  const char* next = "HOME\n";
  for (const char* p = next; *p; ++p) {
    if (r.push(*p)) return !r.overflowed() && equals(r.line(), "HOME");
  }
  return false;
}
static_assert(readerRecoversFromOverflow());

constexpr int kLo[kServoCount] = {0, 0, 0, 0, 0, 0, 0, 0};
constexpr int kHi[kServoCount] = {180, 180, 180, 180, 180, 180, 180, 180};
constexpr int kSign[kFingerCount] = {1, 1, 1, 1};

constexpr bool gripClosesOnlyMaskedFingers() {
  int a[kServoCount] = {20, 20, 20, 20, 160, 160, 160, 160};
  Command g = parse("GRIP:2,600,5");  // finger 1 only
  return gripTick(g, a, 100, kLo, kHi, kSign) == GripResult::Running &&
         a[1] == 25 && a[5] == 155 && a[0] == 20 && a[4] == 160 && a[2] == 20 && a[6] == 160;
}
static_assert(gripClosesOnlyMaskedFingers());

constexpr bool gripStopsOnCurrentWithoutMoving() {
  int a[kServoCount] = {20, 20, 20, 20, 160, 160, 160, 160};
  return gripTick(parse("GRIP:F,600,5"), a, 600, kLo, kHi, kSign) == GripResult::Current && a[0] == 20;
}
static_assert(gripStopsOnCurrentWithoutMoving());

constexpr bool gripStopsOnSensorFailureWithoutMoving() {
  int a[kServoCount] = {20, 20, 20, 20, 160, 160, 160, 160};
  return gripTick(parse("GRIP:F,600,5"), a, -1, kLo, kHi, kSign) == GripResult::Sensor && a[0] == 20 && a[4] == 160;
}
static_assert(gripStopsOnSensorFailureWithoutMoving());

constexpr bool gripStopsAtLimit() {
  int a[kServoCount] = {178, 20, 20, 20, 2, 160, 160, 160};
  Command g = parse("GRIP:1,600,5");
  if (gripTick(g, a, 0, kLo, kHi, kSign) != GripResult::Running || a[0] != 180 || a[4] != 0) return false;
  return gripTick(g, a, 0, kLo, kHi, kSign) == GripResult::Limit;
}
static_assert(gripStopsAtLimit());

}  // namespace proto::selftest
