# hand_firmware

ESP32 firmware for [protocol v1](../../docs/protocol.md). It runs USB serial at 115200 and UDP on port 6000 at the same time.

| File | Job |
|---|---|
| `hand_firmware.ino` | Servo driver, serial + UDP input, replies. Pin map and limits are at the top. |
| `protocol.h` | Pure parser and line splitter (no Arduino calls) |
| `protocol_selftest.h` | `static_assert` tests of the parser. They run on every compile, so a failing case stops the build. |
| `secrets.example.h` | Copy it to `secrets.h` (gitignored). Leave `WIFI_SSID` empty to use serial only. |
| `sketch.yaml` | Default FQBN `esp32:esp32:esp32` |

Tested with core `esp32:esp32` 3.3.12 and the libraries `Adafruit PWM Servo Driver Library` 3.0.3, `Adafruit INA219` 1.2.3 and `Adafruit BusIO` 1.17.4:

```powershell
$cli = "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe"
& $cli lib install "Adafruit PWM Servo Driver Library@3.0.3" "Adafruit INA219@1.2.3"
Copy-Item secrets.example.h secrets.h   # then edit
& $cli compile .
& $cli upload -p COM3 .
& $cli monitor -p COM3 -c baudrate=115200   # type PING, expect PONG v1
```

Wiring: servos on PCA9685 channels 0–7 (servo index = channel), servo power on the PCA9685 `V+` terminal. Two I2C buses, so both boards keep the default address `0x40` and nothing needs soldering: PCA9685 on SDA 21 / SCL 22, INA219 on SDA 18 / SCL 19. Both boards' `VCC` to ESP32 3V3, all grounds common. If the PCA9685 doesn't answer at boot, serial prints `INFO:NOPCA9685` and nothing moves.

Finding dead servos: with servo power on, run `AmazingHand_GUIDesign/servo_check.py`. It moves one servo at a time
and reads the INA219: a turning servo adds a few hundred mA, a dead one or a loose plug adds nothing.

```powershell
cd AmazingHand_GUIDesign
.venv\Scripts\python servo_check.py --port COM6            # channels 0-7 one at a time
.venv\Scripts\python servo_check.py --port COM6 --swap 0   # plug each servo into ch0 in turn: tells servo from channel
```

Done:
- `PING`, `A:`, `HOME`, `STOP`, `STATUS` and `ERR:`, with angles clamped.
- The hand moves to home at boot.
- `GRIP` with INA219 current limiting and the 2 s watchdog. It is refused without a sensor and stops (`GRIP:DONE SENSOR`) if a sensor read fails mid-grip.

Not done yet:
- Real per-servo limits. `kMin`/`kMax` are 0–180 until calibration.
- The real INA219 count and wiring (see `docs/hardware.md`).
- None of this has run on the board yet.
