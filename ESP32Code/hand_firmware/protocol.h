// Protocol v1 parser (docs/protocol.md). Pure C++, no Arduino calls.
// Everything is constexpr so protocol_selftest.h can test it at compile time.
#pragma once
#include <stdint.h>

namespace proto {

constexpr int kServoCount = 8;
constexpr int kMaxLine = 64;

constexpr int kFingerCount = 4;
constexpr int kGripMaxMa = 5000;
constexpr int kGripMaxStep = 20;

enum class Type : uint8_t { None, Angles, Home, Stop, Ping, Status, Grip, Error };
enum class Err : uint8_t { None, Parse, Range, Unknown, NoSensor };

struct Command {
  Type type = Type::None;
  Err err = Err::None;
  int angles[kServoCount] = {};
  uint8_t mask = 0;   // GRIP: bit f = finger f
  int limitMa = 0;    // GRIP: stop when total current reaches this
  int step = 0;       // GRIP: degrees per tick
};

constexpr bool equals(const char* a, const char* b) {
  while (*a && *a == *b) { ++a; ++b; }
  return *a == *b;
}

constexpr Command error(Err e) {
  Command c;
  c.type = Type::Error;
  c.err = e;
  return c;
}

constexpr const char* errName(Err e) {
  switch (e) {
    case Err::Parse: return "PARSE";
    case Err::Range: return "RANGE";
    case Err::Unknown: return "UNKNOWN";
    case Err::NoSensor: return "NOSENSOR";
    default: return "NONE";
  }
}

constexpr int clamp(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Reads 1..maxDigits decimal digits at p. Returns -1 if there are none or too many.
constexpr int readUint(const char*& p, int maxDigits) {
  if (*p < '0' || *p > '9') return -1;
  int v = 0;
  int digits = 0;
  while (*p >= '0' && *p <= '9') {
    if (++digits > maxDigits) return -1;
    v = v * 10 + (*p - '0');
    ++p;
  }
  return v;
}

// Parses one line without its '\n' or '\r'. An empty line gives Type::None and is ignored.
constexpr Command parse(const char* s) {
  Command c;
  if (*s == '\0') return c;
  if (equals(s, "HOME")) { c.type = Type::Home; return c; }
  if (equals(s, "STOP")) { c.type = Type::Stop; return c; }
  if (equals(s, "PING")) { c.type = Type::Ping; return c; }
  if (equals(s, "STATUS")) { c.type = Type::Status; return c; }
  if (s[0] == 'A' && s[1] == ':') {
    const char* p = s + 2;
    for (int i = 0; i < kServoCount; ++i) {
      int v = readUint(p, 3);
      if (v < 0) return error(Err::Parse);
      if (v > 180) return error(Err::Range);
      c.angles[i] = v;
      if (i < kServoCount - 1) {
        if (*p != ',') return error(Err::Parse);
        ++p;
      }
    }
    if (*p != '\0') return error(Err::Parse);
    c.type = Type::Angles;
    return c;
  }
  if (s[0] == 'G' && s[1] == 'R' && s[2] == 'I' && s[3] == 'P' && s[4] == ':') {
    const char* p = s + 5;
    char h = *p++;
    int mask = (h >= '0' && h <= '9') ? h - '0' : (h >= 'A' && h <= 'F') ? h - 'A' + 10 : -1;
    if (mask < 0 || *p++ != ',') return error(Err::Parse);
    int limit = readUint(p, 4);
    if (limit < 0 || *p++ != ',') return error(Err::Parse);
    int step = readUint(p, 2);
    if (step < 0 || *p != '\0') return error(Err::Parse);
    if (mask == 0 || limit == 0 || limit > kGripMaxMa || step == 0 || step > kGripMaxStep) return error(Err::Range);
    c.type = Type::Grip;
    c.mask = static_cast<uint8_t>(mask);
    c.limitMa = limit;
    c.step = step;
    return c;
  }
  return error(Err::Unknown);
}

enum class GripResult : uint8_t { Running, Current, Limit, Sensor };

// One grip tick: stop if the sensor failed (currentMa < 0) or current reached the limit,
// else close each masked finger by step degrees.
// Finger f: servo f moves +sign*step, servo f+4 moves -sign*step (docs/hardware.md mixing), both clamped.
constexpr GripResult gripTick(const Command& g, int angles[kServoCount], int currentMa,
                              const int lo[kServoCount], const int hi[kServoCount], const int flexSign[kFingerCount]) {
  if (currentMa < 0) return GripResult::Sensor;  // never keep closing blind
  if (currentMa >= g.limitMa) return GripResult::Current;
  bool moved = false;
  for (int f = 0; f < kFingerCount; ++f) {
    if (!(g.mask & (1 << f))) continue;
    int a = clamp(angles[f] + flexSign[f] * g.step, lo[f], hi[f]);
    int b = clamp(angles[f + 4] - flexSign[f] * g.step, lo[f + 4], hi[f + 4]);
    moved = moved || a != angles[f] || b != angles[f + 4];
    angles[f] = a;
    angles[f + 4] = b;
  }
  return moved ? GripResult::Running : GripResult::Limit;
}

// Collects bytes into lines. push() returns true when a line is complete; '\r' is dropped.
// A line longer than kMaxLine is discarded up to its '\n' and then reported through overflowed().
class LineReader {
 public:
  constexpr bool push(char ch) {
    if (ch == '\r') return false;
    if (ch == '\n') {
      buf_[len_] = '\0';
      overflowed_ = overflowing_;
      overflowing_ = false;
      len_ = 0;
      return true;
    }
    if (len_ < kMaxLine) buf_[len_++] = ch;
    else overflowing_ = true;
    return false;
  }
  constexpr const char* line() const { return buf_; }
  constexpr bool overflowed() const { return overflowed_; }

 private:
  char buf_[kMaxLine + 1] = {};
  int len_ = 0;
  bool overflowing_ = false;
  bool overflowed_ = false;
};

}  // namespace proto
