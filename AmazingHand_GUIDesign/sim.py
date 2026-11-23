"""MuJoCo twin of the hand, driven by the same protocol lines the ESP32 gets.

Model: ../sim/AH_Right (copied from upstream AmazingHand, see ../sim/README.md).
Run alone to cycle the demo poses: python sim.py
"""
import math
import time
from pathlib import Path

import mujoco
import mujoco.viewer

import hand_model

SCENE = Path(__file__).resolve().parent.parent / "sim" / "AH_Right" / "mjcf" / "scene.xml"

# Our finger f (0 thumb, 1 index, 2 middle, 3 ring) -> upstream finger number; upstream finger4 is the thumb.
UPSTREAM_FINGER = (4, 1, 2, 3)
# Servo index -> sign of (angle - home) in sim radians. Side A = motor1, side B = motor2.
# +1 for all makes +flex close every sim finger toward the thumb (test_sim.py catches a flip of any finger).
# shortcut: the sim matches our mixing convention, not yet the real hand; re-check after calibration.
SIM_SIGN = (1, 1, 1, 1, 1, 1, 1, 1)


def parse_line(line):
    """Servo angles for an A:/HOME/GRIP line, None for anything else."""
    line = line.strip()
    if line == "HOME":
        return list(hand_model.HOME)
    if line.startswith("A:"):
        return [int(v) for v in line[2:].split(",")]
    if line.startswith("GRIP:"):
        # shortcut: no current in the sim, so GRIP just fully closes the masked fingers.
        mask = int(line[5], 16)
        return hand_model.to_servo_angles([1 if mask & (1 << f) else 0 for f in range(len(hand_model.FINGERS))])
    return None


class SimHand:
    def __init__(self, show=True):
        self.model = mujoco.MjModel.from_xml_path(str(SCENE))
        self.data = mujoco.MjData(self.model)
        self.actuator = []
        for i in range(8):
            finger, motor = UPSTREAM_FINGER[i % 4], 1 if i < 4 else 2
            self.actuator.append(self.model.actuator(f"finger{finger}_motor{motor}").id)
        self.viewer = mujoco.viewer.launch_passive(self.model, self.data) if show else None

    def set_angles(self, angles):
        for i, a in enumerate(angles):
            aid = self.actuator[i]
            lo, hi = self.model.actuator_ctrlrange[aid]
            target = SIM_SIGN[i] * math.radians(a - hand_model.HOME[i])
            self.data.ctrl[aid] = min(hi, max(lo, target))

    def handle_line(self, line):
        angles = parse_line(line)
        if angles is not None:
            self.set_angles(angles)

    def step(self, seconds):
        for _ in range(max(1, int(seconds / self.model.opt.timestep))):
            mujoco.mj_step(self.model, self.data)
        if self.viewer is not None:
            self.viewer.sync()

    def tip(self, f):
        return self.data.site(f"tip{UPSTREAM_FINGER[f]}").xpos.copy()

    def close(self):
        if self.viewer is not None:
            self.viewer.close()


if __name__ == "__main__":
    hand = SimHand()
    try:
        while hand.viewer.is_running():
            for name in hand_model.DEMO_POSES:
                hand.set_angles(hand_model.pose_angles(name))
                end = time.time() + 1.5
                while time.time() < end and hand.viewer.is_running():
                    hand.step(0.02)
                    time.sleep(0.02)
    finally:
        hand.close()
