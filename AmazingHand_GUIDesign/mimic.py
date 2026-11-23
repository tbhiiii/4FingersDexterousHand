"""MediaPipe hand landmarks -> finger-space flex (0 open .. 1 closed) for hand_model.

Landmarks are objects with .x .y .z (MediaPipe normalized coordinates); indices follow MediaPipe's hand model.
"""
import math

# (MCP, PIP, TIP) landmark indices for index, middle, ring.
FINGER_JOINTS = ((5, 6, 8), (9, 10, 12), (13, 14, 16))

# shortcut: tuning guesses, check them on a real webcam and adjust.
FULL_BEND_DEG = 120.0   # bend at PIP (MCP-PIP-TIP) that counts as fully closed
THUMB_OPEN_RATIO = 0.55  # |thumb tip - index MCP| / |wrist - middle MCP| when the thumb is open
THUMB_CLOSED_RATIO = 0.20


def _vec(a, b):
    return (b.x - a.x, b.y - a.y, b.z - a.z)


def _dist(a, b):
    return math.sqrt(sum(c * c for c in _vec(a, b)))


def _bend_deg(a, b, c):
    """0 when a-b-c is straight, 90 for a right angle."""
    u, v = _vec(a, b), _vec(b, c)
    nu, nv = math.sqrt(sum(x * x for x in u)), math.sqrt(sum(x * x for x in v))
    if nu == 0 or nv == 0:
        return 0.0
    cos = sum(x * y for x, y in zip(u, v)) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _clip01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def finger_flex(landmarks):
    """Returns flex for (thumb, index, middle, ring), each 0..1."""
    scale = _dist(landmarks[0], landmarks[9])
    if scale == 0:
        thumb = 0.0
    else:
        ratio = _dist(landmarks[4], landmarks[5]) / scale
        thumb = _clip01((THUMB_OPEN_RATIO - ratio) / (THUMB_OPEN_RATIO - THUMB_CLOSED_RATIO))
    fingers = [_clip01(_bend_deg(landmarks[m], landmarks[p], landmarks[t]) / FULL_BEND_DEG)
               for m, p, t in FINGER_JOINTS]
    return [thumb] + fingers
