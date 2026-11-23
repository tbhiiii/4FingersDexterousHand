"""Checks for mimic.py with synthetic landmarks. Run: python test_mimic.py (or pytest)."""
from types import SimpleNamespace as P

import mimic


def hand(finger_tips=None, thumb_tip=(0.5, 0.0, 0.0)):
    """21 landmarks: wrist at origin, middle MCP at (0,1); fingers point up (+y) unless a tip is given."""
    lm = [P(x=0.0, y=0.0, z=0.0) for _ in range(21)]
    lm[9] = P(x=0.0, y=1.0, z=0.0)
    for i, (m, p, t) in enumerate(mimic.FINGER_JOINTS):
        x = -0.2 + 0.2 * i
        lm[m] = P(x=x, y=1.0, z=0.0)
        lm[p] = P(x=x, y=1.3, z=0.0)
        tip = (finger_tips or {}).get(i, (x, 1.6, 0.0))
        lm[t] = P(x=tip[0], y=tip[1], z=tip[2])
    lm[4] = P(x=thumb_tip[0], y=thumb_tip[1], z=thumb_tip[2])
    return lm


def close(a, b):
    return abs(a - b) < 1e-6


def test_straight_fingers_are_open():
    flex = mimic.finger_flex(hand(thumb_tip=(-0.2 + 0.6, 1.0, 0.0)))  # thumb tip 0.6 from index MCP
    assert all(close(f, 0.0) for f in flex), flex


def test_right_angle_bend_maps_to_ratio_of_full_bend():
    flex = mimic.finger_flex(hand({0: (0.1, 1.3, 0.0)}))  # index tip turns 90 deg at PIP
    assert close(flex[1], 90.0 / mimic.FULL_BEND_DEG), flex
    assert close(flex[2], 0.0) and close(flex[3], 0.0)


def test_folded_finger_is_clipped_to_one():
    flex = mimic.finger_flex(hand({1: (0.0, 1.0, 0.0)}))  # middle tip folds back to MCP: 180 deg
    assert close(flex[2], 1.0), flex


def test_thumb_on_index_mcp_is_closed():
    flex = mimic.finger_flex(hand(thumb_tip=(-0.2, 1.0, 0.0)))
    assert close(flex[0], 1.0), flex


def test_degenerate_hand_does_not_crash():
    lm = [P(x=0.0, y=0.0, z=0.0) for _ in range(21)]
    assert mimic.finger_flex(lm) == [0.0, 0.0, 0.0, 0.0]


if __name__ == "__main__":
    tests = [f for n, f in sorted(globals().items()) if n.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)} tests passed")
