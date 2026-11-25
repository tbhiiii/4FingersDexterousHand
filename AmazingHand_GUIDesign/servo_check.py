"""Find dead servos: move each one a little and watch the INA219 current.

A servo that turns draws a few hundred mA; a dead one draws nothing. Needs the ESP32 flashed with
hand_firmware, servo power connected through the INA219, and the hand free to move a little.

From AmazingHand_GUIDesign:
  .venv\\Scripts\\python servo_check.py --port COM6            # move channels 0-7 one at a time
  .venv\\Scripts\\python servo_check.py --port COM6 --swap 0   # plug every servo into ch0, one by one
"""
import argparse
import time

import serial

import hand_model

MARGIN_MA = 40  # a turning servo adds far more than this over the idle current


def parse_current(line):
    """'ST:20,...;I:51' -> 51. None if there is no reading (no sensor: 'I:NA')."""
    if ";I:" not in line:
        return None
    try:
        return sum(int(v) for v in line.split(";I:")[1].split(","))
    except ValueError:
        return None


def moved(peak_ma, idle_ma):
    return peak_ma - idle_ma >= MARGIN_MA


class Hand:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=0.02)
        deadline = time.time() + 5
        while time.time() < deadline:  # opening the port can reset the ESP32; wait until it answers
            if self.ask("PING").startswith("PONG"):
                return
        raise SystemExit(f"No PONG from {port}. Is hand_firmware flashed and the port right?")

    def ask(self, cmd):
        self.s.reset_input_buffer()
        self.s.write((cmd + "\n").encode())
        buf, end = b"", time.time() + 0.15
        while b"\n" not in buf and time.time() < end:
            buf += self.s.read(256)
        return buf.decode(errors="replace").strip()

    def move(self, angles):
        self.s.write(("A:" + ",".join(str(a) for a in angles) + "\n").encode())

    def peak(self, seconds):
        vals, end = [], time.time() + seconds
        while time.time() < end:
            v = parse_current(self.ask("STATUS"))
            if v is not None:
                vals.append(v)
        return max(vals) if vals else None


def test_channel(hand, ch, deg, idle):
    target = list(hand_model.HOME)
    target[ch] += deg if ch < 4 else -deg  # same closing direction as the firmware's mixing
    hand.move(target)
    out = hand.peak(1.0)
    hand.move(hand_model.HOME)
    back = hand.peak(1.0)
    peak = max(out, back)
    return peak, moved(peak, idle)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default="COM6")
    p.add_argument("--deg", type=int, default=40, help="how far each servo moves from home (5-60)")
    p.add_argument("--swap", type=int, metavar="CH", help="test servos one by one on this channel")
    args = p.parse_args()
    deg = max(5, min(60, args.deg))

    hand = Hand(args.port)
    if parse_current(hand.ask("STATUS")) is None:
        raise SystemExit("STATUS shows no current reading (I:NA): check the INA219 wiring (SDA 18 / SCL 19).")
    hand.move(hand_model.HOME)
    time.sleep(1.0)
    idle = hand.peak(0.8)
    print(f"Idle current: {idle} mA. A servo counts as working if it adds >= {MARGIN_MA} mA while moving.\n")

    results = []
    try:
        if args.swap is None:
            for ch in range(8):
                peak, ok = test_channel(hand, ch, deg, idle)
                results.append((f"ch{ch}", peak, ok))
                print(f"ch{ch}: peak {peak:4d} mA  {'OK' if ok else 'NO MOVEMENT'}")
                time.sleep(0.3)
        else:
            n = 1
            while True:
                label = input(f"Plug servo #{n} into ch{args.swap}, then type a name and Enter (empty = #{n}, q = done): ").strip()
                if label.lower() == "q":
                    break
                label = label or f"#{n}"
                peak, ok = test_channel(hand, args.swap, deg, idle)
                results.append((label, peak, ok))
                print(f"  {label}: peak {peak} mA  {'OK' if ok else 'NO MOVEMENT'}")
                n += 1
    finally:
        hand.move(hand_model.HOME)

    dead = [name for name, _, ok in results if not ok]
    print(f"\nTested {len(results)}, working {len(results) - len(dead)}, not moving {len(dead)}: {', '.join(dead) or 'none'}")
    if args.swap is None and dead:
        print("A failing channel can be a dead servo or a loose plug. Re-run with --swap on a working channel to tell which.")


if __name__ == "__main__":
    main()
