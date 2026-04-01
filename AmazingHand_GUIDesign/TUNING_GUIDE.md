# Hand Tracking Parameter Tuning Guide

This guide lists practical tuning ranges and how each knob affects stability vs. responsiveness. Use it for both `main.py` and `main_v2.py`.

## Quick Start (Stable but not obviously slow)
Set these first and test:

- `PINCH_ON_RATIO = 0.24`
- `PINCH_OFF_RATIO = 0.40~0.45`
- `PINCH_STABLE_SEC = 0.12~0.16`
- `CLICK_COOLDOWN_SEC = 0.4~0.7`
- `ONE_EURO_MIN_CUTOFF = 1.4~1.8`
- `ONE_EURO_BETA = 0.01~0.03`
- `ONE_EURO_PINCH_MIN_CUTOFF = 1.8~2.5`
- `CURSOR_MEDIAN_WINDOW = 5`
- `CURSOR_DEADZONE_PX = 2~3`
- `CURSOR_MAX_STEP_PX = 18~28`
- `CURSOR_MAX_STEP_RATIO = 0.6~0.8`
- `MAX_NUM_HANDS = 1`
- `MIN_DETECTION_CONFIDENCE = 0.6~0.8`
- `MIN_TRACKING_CONFIDENCE = 0.5~0.7`

## Parameter Reference

### MediaPipe / Camera
- `CAP_WIDTH`, `CAP_HEIGHT`
  - Higher resolution gives more stable landmarks but costs FPS.
  - Suggested range: `640x360` to `1280x720`.
- `MAX_NUM_HANDS`
  - More hands can cause switching jitter.
  - Use `1` for stability, `2` only if you need it.
- `MIN_DETECTION_CONFIDENCE`
  - Too high: hand drops out. Too low: noisy detection.
  - Suggested range: `0.6~0.85`.
- `MIN_TRACKING_CONFIDENCE`
  - Higher = steadier tracking, but more dropouts.
  - Suggested range: `0.5~0.8`.
- `MIN_PRESENCE_CONFIDENCE` (Tasks API only)
  - Suggested range: `0.5~0.8`.
- `USE_STATIC_IMAGE_MODE`
  - Keep `False` for real-time tracking stability.

### Pinch Detection
- `PINCH_ON_RATIO`
  - Smaller = harder to trigger, more stable.
  - Suggested range: `0.22~0.28`.
- `PINCH_OFF_RATIO`
  - Larger = more hysteresis (reduces flicker).
  - Suggested range: `0.36~0.45`.
- `PINCH_STABLE_SEC`
  - Hold time required to accept a pinch as a click trigger.
  - Suggested range: `0.10~0.18`.
- `CLICK_COOLDOWN_SEC`
  - Prevents rapid double-triggering.
  - Suggested range: `0.4~0.8`.

### Cursor Smoothing (One Euro Filter)
- `USE_ONE_EURO`
  - Keep `True` for best stability.
- `ONE_EURO_MIN_CUTOFF`
  - Lower = smoother but slower.
  - Suggested range: `1.2~2.0`.
- `ONE_EURO_BETA`
  - Higher = less lag during fast movement.
  - Suggested range: `0.01~0.05`.
- `ONE_EURO_D_CUTOFF`
  - Smoothing for speed term.
  - Suggested range: `0.5~2.0`.
- `ONE_EURO_PINCH_MIN_CUTOFF`, `ONE_EURO_PINCH_BETA`
  - For pinch ratio smoothing.
  - Suggested range: `1.6~3.0` and `0.005~0.03`.

### Cursor Anti-Jitter
- `USE_CURSOR_MEDIAN`
  - Keep `True` for stability.
- `CURSOR_MEDIAN_WINDOW`
  - Larger window = smoother but adds delay.
  - Suggested range: `3~7`.
- `CURSOR_DEADZONE_PX`
  - Ignores tiny noise.
  - Suggested range: `1~4`.
- `CURSOR_MAX_STEP_PX`
  - Limits sudden jumps.
  - Suggested range: `14~32`.
- `CURSOR_MAX_STEP_RATIO`
  - Limits jump based on palm width.
  - Suggested range: `0.5~0.9`.
- `USE_PALM_ANCHOR`
  - Stabilizes using palm center. Keep `True` unless you want faster pointer response.

## Tuning Strategy
1. Lock the camera first: good light, steady exposure, higher FPS.
2. Set `MAX_NUM_HANDS = 1`.
3. Tune `ONE_EURO_MIN_CUTOFF` and `ONE_EURO_BETA` until motion feels stable but not laggy.
4. Add `CURSOR_DEADZONE_PX` and `CURSOR_MAX_STEP_PX` to kill micro-jitter and spikes.
5. Adjust `PINCH_ON_RATIO` / `PINCH_OFF_RATIO` to stop flicker.
6. Use `PINCH_STABLE_SEC` + `CLICK_COOLDOWN_SEC` to stop repeat triggers.

## Common Symptoms
- Cursor trembles while hand is still:
  - Increase `ONE_EURO_MIN_CUTOFF` slightly lower (smoother)
  - Increase `CURSOR_DEADZONE_PX`
  - Increase `CURSOR_MEDIAN_WINDOW`
- Cursor lags too much:
  - Increase `ONE_EURO_BETA`
  - Reduce `CURSOR_MEDIAN_WINDOW`
  - Reduce `CURSOR_DEADZONE_PX`
- Pinch triggers repeatedly:
  - Increase `PINCH_OFF_RATIO`
  - Increase `PINCH_STABLE_SEC`
  - Increase `CLICK_COOLDOWN_SEC`

