"""Checks for servo_check.py (no hardware). Run: .venv\\Scripts\\python test_servo_check.py"""
import servo_check


def test_parse_current():
    assert servo_check.parse_current("ST:20,20,20,20,160,160,160,160;I:51") == 51
    assert servo_check.parse_current("ST:20,20,20,20,160,160,160,160;I:30,-5") == 25  # several sensors are summed
    assert servo_check.parse_current("ST:20,20,20,20,160,160,160,160;I:NA") is None
    assert servo_check.parse_current("PONG v1") is None
    assert servo_check.parse_current("") is None


def test_moved_threshold():
    assert servo_check.moved(396, 50)
    assert not servo_check.moved(62, 50)
    assert servo_check.moved(50 + servo_check.MARGIN_MA, 50)


if __name__ == "__main__":
    tests = [f for n, f in sorted(globals().items()) if n.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)} tests passed")
