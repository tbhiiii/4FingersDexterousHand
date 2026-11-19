"""Headless checks for sim.py (needs mujoco). Run: .venv\\Scripts\\python test_sim.py"""
import numpy as np

import hand_model
import sim


def settle(hand, angles, seconds=1.0):
    hand.set_angles(angles)
    hand.step(seconds)
    wrist = hand.data.body("r_wrist_interface").xpos
    return [float(np.linalg.norm(hand.tip(f) - wrist)) for f in range(4)]


def test_parse_line():
    assert sim.parse_line("HOME\n") == list(hand_model.HOME)
    assert sim.parse_line("A:1,2,3,4,5,6,7,8") == [1, 2, 3, 4, 5, 6, 7, 8]
    assert sim.parse_line("PING") is None
    assert sim.parse_line("GRIP:F,600,2") == hand_model.pose_angles("FIST")
    assert sim.parse_line("GRIP:1,600,2") == hand_model.to_servo_angles((1, 0, 0, 0))


def test_flex_closes_every_finger():
    hand = sim.SimHand(show=False)
    open_d = settle(hand, hand_model.pose_angles("OPEN"))
    fist_d = settle(hand, hand_model.pose_angles("FIST"))
    for f, (o, c) in enumerate(zip(open_d, fist_d)):
        assert c < o - 0.005, f"finger {hand_model.FINGERS[f]}: tip-wrist {o:.4f} -> {c:.4f} m, expected to close"


def test_flex_direction_opposes_thumb():
    # Bending backwards also shortens tip-wrist, so check direction: thumb + finger flex must close their gap.
    for f in (1, 2, 3):
        hand = sim.SimHand(show=False)
        settle(hand, hand_model.to_servo_angles((0, 0, 0, 0)))
        before = float(np.linalg.norm(hand.tip(0) - hand.tip(f)))
        flex = [0.6 if i in (0, f) else 0 for i in range(4)]
        settle(hand, hand_model.to_servo_angles(flex))
        after = float(np.linalg.norm(hand.tip(0) - hand.tip(f)))
        assert after < before - 0.01, f"thumb-{hand_model.FINGERS[f]} gap {before:.4f} -> {after:.4f} m"


def test_home_line_returns_to_open():
    hand = sim.SimHand(show=False)
    open_d = settle(hand, hand_model.pose_angles("OPEN"))
    settle(hand, hand_model.pose_angles("FIST"))
    hand.handle_line("HOME")
    hand.step(1.0)
    wrist = hand.data.body("r_wrist_interface").xpos
    back = [float(np.linalg.norm(hand.tip(f) - wrist)) for f in range(4)]
    assert np.allclose(back, open_d, atol=0.003), (open_d, back)


if __name__ == "__main__":
    tests = [f for n, f in sorted(globals().items()) if n.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)} tests passed")
