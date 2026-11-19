"""Protocol v1 command encoders (docs/protocol.md).

Mirror of ESP32Code/hand_firmware/protocol.h: change both together.
"""

SERVO_COUNT = 8
HOME = "HOME"
STOP = "STOP"
PING = "PING"
STATUS = "STATUS"


def grip(mask, limit_ma, step_deg):
    """Close fingers in mask (bit f = finger f) until total current reaches limit_ma."""
    if not (1 <= mask <= 0xF and 1 <= limit_ma <= 5000 and 1 <= step_deg <= 20):
        raise ValueError(f"bad GRIP args: mask={mask} limit_ma={limit_ma} step_deg={step_deg}")
    return f"GRIP:{mask:X},{int(limit_ma)},{int(step_deg)}"


def angles(values):
    values = [int(v) for v in values]
    if len(values) != SERVO_COUNT or not all(0 <= v <= 180 for v in values):
        raise ValueError(f"need {SERVO_COUNT} angles in 0..180, got {values}")
    return "A:" + ",".join(str(v) for v in values)
