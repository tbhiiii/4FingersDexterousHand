# sim

MuJoCo digital twin of the hand.

## Source and license

`AH_Right/mjcf/` holds the MJCF files (`*.xml`, `config.json`) and the meshes (`assets/*.stl`). They are copied unchanged from
[`pollen-robotics/AmazingHand`](https://github.com/pollen-robotics/AmazingHand), path `Demo/AHSimulation/AHSimulation/AH_Right/mjcf`,
at commit `3e8241074df3436a3044ced4881e3bb2133aa725`. The CAD intermediates (`*.part`) were left out.

- Code: Apache-2.0 ([LICENSE](LICENSE), copied from upstream)
- Mechanical design: CC BY 4.0, © Pollen Robotics

## Usage

The model is driven by `AmazingHand_GUIDesign/sim.py`. That code takes the same `A:`/`HOME` lines the ESP32 gets and maps
servo index → upstream actuator `finger<n>_motor<1|2>`. Upstream `finger4` is the thumb.

```powershell
cd AmazingHand_GUIDesign
.venv\Scripts\python sim.py                    # cycle the 5 demo poses in a viewer
.venv\Scripts\python main_v2.py --target sim   # webcam drives the twin, no ESP32 needed
.venv\Scripts\python main_v2.py --target both  # drive the real hand and the twin together
```

Our hand uses PWM servos mounted with their own home angles, so the mapping `sim_rad = SIM_SIGN * radians(angle - HOME)` is
an approximation. Re-check `SIM_SIGN` in `sim.py` after the real hand is calibrated.
