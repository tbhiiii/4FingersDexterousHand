"""Checks for hand_model.py and protocol.py. Run: python test_hand_model.py (or pytest)."""
import re

import hand_model
import protocol

# Same shape the firmware parser accepts (protocol.h): 8 fields, 1-3 digits each.
FIRMWARE_A = re.compile(r"^A:(\d{1,3},){7}\d{1,3}$")


def test_open_is_home():
    assert hand_model.to_servo_angles((0, 0, 0, 0)) == list(hand_model.HOME)


def test_flex_moves_pair_in_opposite_directions():
    a = hand_model.to_servo_angles((1, 0, 0, 0))
    assert a[0] == 20 + hand_model.FLEX_RANGE_DEG
    assert a[4] == 160 - hand_model.FLEX_RANGE_DEG
    assert a[1:4] == [20, 20, 20] and a[5:] == [160, 160, 160]


def test_abd_moves_pair_together():
    a = hand_model.to_servo_angles((0, 0, 0, 0), (0, 0.5, 0, 0))
    shift = round(0.5 * hand_model.ABD_RANGE_DEG)
    assert a[1] == 20 + shift and a[5] == 160 + shift


def test_out_of_range_input_is_clipped():
    a = hand_model.to_servo_angles((5, -5, 0, 0), (-9, 9, 0, 0))
    assert all(0 <= v <= 180 for v in a)


def test_every_pose_encodes_to_valid_firmware_line():
    for name in hand_model.POSES:
        line = protocol.angles(hand_model.pose_angles(name))
        assert FIRMWARE_A.match(line), (name, line)


def test_rps_and_demo_poses_exist():
    assert set(hand_model.RPS_POSE) == {"ROCK", "PAPER", "SCISSORS"}
    assert all(p in hand_model.POSES for p in hand_model.RPS_POSE.values())
    assert all(p in hand_model.POSES for p in hand_model.DEMO_POSES) and len(hand_model.DEMO_POSES) == 5


def test_protocol_rejects_bad_angles():
    for bad in ([0] * 7, [0] * 9, [181] + [0] * 7, [-1] + [0] * 7):
        try:
            protocol.angles(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_protocol_grip_matches_firmware_format():
    assert protocol.grip(0xF, 600, 2) == "GRIP:F,600,2"
    assert re.match(r"^GRIP:[0-9A-F],\d{1,4},\d{1,2}$", protocol.grip(0x3, 5000, 20))
    for bad in ((0, 600, 2), (0x10, 600, 2), (0xF, 0, 2), (0xF, 5001, 2), (0xF, 600, 21)):
        try:
            protocol.grip(*bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_firmware_constants_match():
    # GRIP closes fingers on the ESP32 with kHome/kFlexSign; they must equal the PC's HOME/FLEX_SIGN.
    from pathlib import Path
    ino = (Path(__file__).resolve().parent.parent / "ESP32Code" / "hand_firmware" / "hand_firmware.ino").read_text()

    def initializer(name):
        m = re.search(r"\b" + name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", ino)
        assert m, f"{name} not found in hand_firmware.ino"
        return tuple(int(v) for v in m.group(1).split(","))

    assert initializer("kHome") == tuple(hand_model.HOME), "kHome != hand_model.HOME"
    assert initializer("kFlexSign") == tuple(hand_model.FLEX_SIGN), "kFlexSign != hand_model.FLEX_SIGN"


if __name__ == "__main__":
    tests = [f for n, f in sorted(globals().items()) if n.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)} tests passed")
