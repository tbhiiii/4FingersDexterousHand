# 4FingersDexterousHand

**EN** · A 4-finger, 8-servo robotic hand you control with your own hand in front of a webcam. Student
learning project, forked from [pollen-robotics/AmazingHand](https://github.com/pollen-robotics/AmazingHand)
(Apache-2.0), rebuilt around PWM servos and an ESP32.

**中文** · 一只 4 指、8 舵机的机械手，用摄像头识别你的手来控制它。这是学生学习项目，参考并 fork 自
[pollen-robotics/AmazingHand](https://github.com/pollen-robotics/AmazingHand)（Apache-2.0），改用 PWM 舵机和 ESP32。

## Features · 功能 (v1)

| EN | 中文 | Status · 状态 |
|---|---|---|
| Rock-paper-scissors against the hand | 和机械手玩剪刀石头布 | code done, not tested on the hand · 代码完成，未上实机 |
| 5 demo poses | 5 个演示动作 | code done, not tested on the hand · 代码完成，未上实机 |
| Mimic: the hand copies yours (flex only) | 模仿：机械手跟着你的手动（仅弯曲） | code done, not tested on the hand · 代码完成，未上实机 |
| MuJoCo digital twin | MuJoCo 同步模拟 | code done, not tested on the hand · 代码完成，未上实机 |
| Handshake with grip-force limit | 握手（限制握力） | code done, not tested on the hand · 代码完成，未上实机 |

More ideas and milestones · 更多想法与里程碑: [docs/features.md](docs/features.md)

## How it works · 原理

```
webcam → MediaPipe (PC) → mode (RPS / mimic / handshake) → 8 servo angles → UDP or USB serial → ESP32 → servos
                                                                         ↘ MuJoCo twin
```

The PC does all the computing; the ESP32 only drives the servos and limits the grip current. · 所有计算在电脑上完成，ESP32 只负责驱动舵机和限制握力电流。
Details · 详情: [docs/architecture.md](docs/architecture.md), [docs/protocol.md](docs/protocol.md), [docs/hardware.md](docs/hardware.md)

## Quick start · 快速开始

```powershell
cd AmazingHand_GUIDesign
uv venv .venv --python 3.13
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python main_v2.py --device 0 --target sim
```

`--target hw|sim|both`: real hand over UDP/serial, MuJoCo twin, or both. · `--target` 选择实机、仿真或两者。
Pinch your thumb and index finger to click the on-screen buttons. · 拇指和食指捏合即可点击屏幕上的按钮。
Tuning · 调参: [AmazingHand_GUIDesign/TUNING_GUIDE.md](AmazingHand_GUIDesign/TUNING_GUIDE.md)

Firmware build commands · 固件编译命令: [ESP32Code/hand_firmware/README.md](ESP32Code/hand_firmware/README.md)

## Repo layout · 目录

| Path | EN | 中文 |
|---|---|---|
| `AmazingHand_GUIDesign/` | PC app (Python, MediaPipe) | 电脑端程序 |
| `ESP32Code/` | Firmware (Arduino, arduino-cli) | 固件 |
| `sim/` | MuJoCo model + twin | MuJoCo 模型与同步模拟 |
| `docs/` | Architecture, protocol, hardware, decisions | 架构、协议、硬件、决策 |

## Credits · 致谢

Mechanical design and simulation model: [Pollen Robotics AmazingHand](https://github.com/pollen-robotics/AmazingHand)
(code Apache-2.0, mechanics CC BY 4.0). · 机械设计与仿真模型来自 Pollen Robotics AmazingHand。
