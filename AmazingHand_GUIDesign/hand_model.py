"""Finger-space poses -> 8 servo angles. The only place that knows servo angles.

Finger f (0 thumb, 1 index, 2 middle, 3 ring) drives servo f (side A) and servo f+4 (side B).
Mixing (docs/hardware.md, differential mixing): A = home_A + sign*F + S, B = home_B - sign*F + S.
flex: 0 = open, 1 = closed. abd: -1..1 sideways.
"""

FINGERS = ("thumb", "index", "middle", "ring")
HOME = (20, 20, 20, 20, 160, 160, 160, 160)

# shortcut: placeholders until the hand is calibrated (docs/hardware.md calibration table); then set per finger.
FLEX_SIGN = (1, 1, 1, 1)
FLEX_RANGE_DEG = 90
ABD_RANGE_DEG = 20

# name: (flex per finger, abd per finger)
POSES = {
    "OPEN": ((0, 0, 0, 0), (0, 0, 0, 0)),
    "FIST": ((1, 1, 1, 1), (0, 0, 0, 0)),
    "POINT": ((1, 0, 1, 1), (0, 0, 0, 0)),
    "PEACE": ((1, 0, 0, 1), (0, -0.5, 0.5, 0)),
    "PINCH": ((0.6, 0.6, 0, 0), (0, 0, 0, 0)),
}
DEMO_POSES = ("OPEN", "FIST", "POINT", "PEACE", "PINCH")
RPS_POSE = {"ROCK": "FIST", "PAPER": "OPEN", "SCISSORS": "PEACE"}


def _clip(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def to_servo_angles(flex, abd=(0, 0, 0, 0)):
    angles = list(HOME)
    for f in range(len(FINGERS)):
        F = FLEX_SIGN[f] * _clip(flex[f], 0.0, 1.0) * FLEX_RANGE_DEG
        S = _clip(abd[f], -1.0, 1.0) * ABD_RANGE_DEG
        angles[f] = HOME[f] + F + S
        angles[f + 4] = HOME[f + 4] - F + S
    return [int(round(_clip(a, 0, 180))) for a in angles]


def pose_angles(name):
    flex, abd = POSES[name]
    return to_servo_angles(flex, abd)
