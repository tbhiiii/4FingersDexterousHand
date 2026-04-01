import argparse
import math
import random
import socket
import time
import urllib.request
from collections import deque
from pathlib import Path

import cv2 as cv
import mediapipe as mp

try:
    import serial  # type: ignore
except Exception:
    serial = None

# Check if the current environment uses the newer Tasks API (MediaPipe 0.10+ / Python 3.13+)
# The older 'mp.solutions' API is deprecated in newer versions.
use_tasks_api = not hasattr(mp, "solutions")

# Model URLs and local paths for the Tasks API hand landmarker model
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"

# ================= Runtime Tuning Parameters =================
ENABLE_GPU = False  # Try GPU delegate for Tasks API if available (may require specific hardware setups).
CAP_WIDTH = 960
CAP_HEIGHT = 540
MAX_NUM_HANDS = 1
MIN_DETECTION_CONFIDENCE = 0.7
MIN_TRACKING_CONFIDENCE = 0.5
MIN_PRESENCE_CONFIDENCE = 0.5
USE_STATIC_IMAGE_MODE = False

PINCH_ON_RATIO = 0.24
PINCH_OFF_RATIO = 0.42
PINCH_STABLE_SEC = 0.12
CLICK_COOLDOWN_SEC = 0.5

CURSOR_SMOOTHING = 0.7
USE_ONE_EURO = True
ONE_EURO_MIN_CUTOFF = 1.6
ONE_EURO_BETA = 0.015
ONE_EURO_D_CUTOFF = 1.0
ONE_EURO_PINCH_MIN_CUTOFF = 2.0
ONE_EURO_PINCH_BETA = 0.01

USE_CURSOR_MEDIAN = True
CURSOR_MEDIAN_WINDOW = 5
CURSOR_DEADZONE_PX = 2
CURSOR_MAX_STEP_PX = 24
CURSOR_MAX_STEP_RATIO = 0.7
USE_PALM_ANCHOR = True

CLICK_COUNTDOWN_SEC = 3.0
GAME_COUNTDOWN_SEC = 3.0
GAME_REVEAL_SEC = 2.0

FLIP_IMAGE = True
MIMIC_HAND_LABEL = "Left" if FLIP_IMAGE else "Right"

# ================= Transport Configuration (ESP32) =================
CONTROL_TRANSPORT = "udp"  # "serial" | "udp" | "both"
SERIAL_ENABLED = False
SERIAL_PORT = "COM3"
SERIAL_BAUD = 115200
SERIAL_SEND_INTERVAL = 0.08
SERIAL_LOG = True

UDP_ENABLED = True
UDP_IP = "192.168.1.50"
UDP_PORT = 6000
WEBCAMID = 0


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=WEBCAMID)
    parser.add_argument("--width", type=int, default=CAP_WIDTH)
    parser.add_argument("--height", type=int, default=CAP_HEIGHT)
    parser.add_argument("--max_num_hands", type=int, default=MAX_NUM_HANDS)
    parser.add_argument("--use_static_image_mode", action="store_true")
    parser.add_argument("--min_detection_confidence", type=float, default=MIN_DETECTION_CONFIDENCE)
    parser.add_argument("--min_tracking_confidence", type=float, default=MIN_TRACKING_CONFIDENCE)
    return parser.parse_args()


def _use_serial():
    return CONTROL_TRANSPORT in ("serial", "both")


def _use_udp():
    return CONTROL_TRANSPORT in ("udp", "both")


def _send_cmd(cmd, serial_port, udp_socket):
    sent = False
    if _use_serial():
        if serial_port is not None:
            serial_port.write((cmd + "\n").encode("ascii", errors="ignore"))
            sent = True
        elif SERIAL_LOG:
            print(f"[SERIAL DISABLED] {cmd}")

    if _use_udp():
        if udp_socket is not None:
            udp_socket.sendto((cmd + "\n").encode("ascii", errors="ignore"), (UDP_IP, UDP_PORT))
            sent = True
        elif SERIAL_LOG:
            print(f"[UDP DISABLED] {cmd}")

    if not sent and SERIAL_LOG:
        print(f"[NO TRANSPORT] {cmd}")


def _draw_center_text(img, text, y, scale, color, thickness=2):
    text_size = cv.getTextSize(text, cv.FONT_HERSHEY_SIMPLEX, scale, thickness)[0]
    x = (img.shape[1] - text_size[0]) // 2
    cv.putText(img, text, (x, y), cv.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


class _LowPassFilter:
    def __init__(self, alpha, initial=None):
        self.alpha = alpha
        self.s = initial

    def reset(self):
        self.s = None

    def apply(self, value):
        if self.s is None:
            self.s = value
        else:
            self.s = self.alpha * value + (1.0 - self.alpha) * self.s
        return self.s


class OneEuroFilter:
    def __init__(self, min_cutoff=1.0, beta=0.0, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPassFilter(1.0)
        self._dx = _LowPassFilter(1.0)
        self._last = None

    def reset(self):
        self._x.reset()
        self._dx.reset()
        self._last = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def apply(self, value, dt):
        if dt <= 0:
            return value
        if self._last is None:
            self._last = value
        dx = (value - self._last) / dt
        self._last = value

        alpha_d = self._alpha(self.d_cutoff, dt)
        self._dx.alpha = alpha_d
        edx = self._dx.apply(dx)

        cutoff = self.min_cutoff + self.beta * abs(edx)
        alpha = self._alpha(cutoff, dt)
        self._x.alpha = alpha
        return self._x.apply(value)


class VirtualButton:
    def __init__(self, x, y, w, h, text):
        self.rect = (x, y, w, h)
        self.text = text
        self.is_hovered = False
        self.is_clicked = False
        self.color_normal = (150, 50, 50)
        self.color_hover = (255, 150, 0)
        self.color_click = (0, 200, 0)
        self.text_color = (255, 255, 255)

    def update(self, cursor, is_pinch):
        if cursor is None:
            self.is_hovered = False
            self.is_clicked = False
            return
        cx, cy = cursor
        x, y, w, h = self.rect
        self.is_hovered = (x <= cx <= x + w) and (y <= cy <= y + h)
        if not is_pinch:
            self.is_clicked = False

    def draw(self, img):
        x, y, w, h = self.rect
        if self.is_clicked:
            bg_color = self.color_click
        elif self.is_hovered:
            bg_color = self.color_hover
        else:
            bg_color = self.color_normal
        cv.rectangle(img, (x, y), (x + w, y + h), bg_color, -1)
        cv.rectangle(img, (x, y), (x + w, y + h), (255, 255, 255), 2)
        text_size = cv.getTextSize(self.text, cv.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
        text_x = x + (w - text_size[0]) // 2
        text_y = y + (h + text_size[1]) // 2
        cv.putText(img, self.text, (text_x, text_y), cv.FONT_HERSHEY_SIMPLEX, 0.7, self.text_color, 2)


def _draw_click_countdown(img, cursor, elapsed, duration):
    if cursor is None or duration <= 0:
        return
    progress = min(1.0, max(0.0, elapsed / duration))
    radius = 22
    thickness = 3
    base_color = (210, 210, 210)
    arc_color = (255, 255, 255)
    cv.circle(img, cursor, radius, base_color, 1)
    start_angle = -90
    end_angle = start_angle + (progress * 360.0)
    cv.ellipse(img, cursor, (radius, radius), 0, start_angle, end_angle, arc_color, thickness)


def _to_pixel(lm, w, h):
    return int(lm.x * w), int(lm.y * h)


def _dist2(a, b):
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy


def _label_from_classification_list(classification_list):
    if classification_list is None:
        return None
    if hasattr(classification_list, "classification"):
        classification_list = classification_list.classification
    if not classification_list:
        return None
    first = classification_list[0]
    return getattr(first, "category_name", None) or getattr(first, "label", None)


def _is_open_hand(landmarks):
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    extended = sum(1 for tip_i, pip_i in zip(tips, pips) if landmarks[tip_i].y < landmarks[pip_i].y)
    return extended >= 3


def _is_fist(landmarks):
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    curled = sum(1 for tip_i, pip_i in zip(tips, pips) if landmarks[tip_i].y > landmarks[pip_i].y)
    return curled >= 3


def _hand_scale2(landmarks):
    return _dist2(landmarks[5], landmarks[17])


def _hand_scale_px(landmarks, w, h):
    x1, y1 = _to_pixel(landmarks[5], w, h)
    x2, y2 = _to_pixel(landmarks[17], w, h)
    return math.hypot(x1 - x2, y1 - y2)


def _palm_center_px(landmarks, w, h):
    indices = (0, 5, 9, 13, 17)
    sx = 0.0
    sy = 0.0
    for idx in indices:
        lm = landmarks[idx]
        sx += lm.x
        sy += lm.y
    cx = sx / len(indices)
    cy = sy / len(indices)
    return int(cx * w), int(cy * h)


def _thumb_open(landmarks):
    scale2 = _hand_scale2(landmarks)
    if scale2 <= 0:
        return False
    ratio2 = _dist2(landmarks[4], landmarks[5]) / scale2
    return ratio2 > (0.32 * 0.32)


def _finger_states(landmarks):
    return {
        "thumb": _thumb_open(landmarks),
        "index": landmarks[8].y < landmarks[6].y,
        "middle": landmarks[12].y < landmarks[10].y,
        "ring": landmarks[16].y < landmarks[14].y,
        "pinky": landmarks[20].y < landmarks[18].y,
    }


def _rps_from_landmarks(landmarks):
    states = _finger_states(landmarks)
    extended = [states["index"], states["middle"], states["ring"], states["pinky"]]
    extended_count = sum(1 for v in extended if v)
    if extended_count <= 1:
        return "ROCK"
    if states["index"] and states["middle"] and not states["ring"] and not states["pinky"]:
        return "SCISSORS"
    if extended_count >= 3:
        return "PAPER"
    return "UNKNOWN"


def _rps_winner(user_move, robot_move):
    if user_move in ("NONE", "UNKNOWN"):
        return "ROBOT"
    if user_move == robot_move:
        return "DRAW"
    wins = {
        ("ROCK", "SCISSORS"),
        ("SCISSORS", "PAPER"),
        ("PAPER", "ROCK"),
    }
    return "USER" if (user_move, robot_move) in wins else "ROBOT"


def _find_hand_by_label(hands, label):
    for info in hands:
        if info.get("label") == label:
            return info.get("landmarks")
    return None


def _select_control_hand(hands, cursor, w, h):
    if not hands:
        return None, None, None
    if cursor is None:
        info = hands[0]
        landmarks = info["landmarks"]
        return landmarks, _to_pixel(landmarks[8], w, h), info.get("label")
    best_info = None
    best_tip = None
    best_dist2 = None
    for info in hands:
        landmarks = info["landmarks"]
        ix, iy = _to_pixel(landmarks[8], w, h)
        dist2 = (ix - cursor[0]) ** 2 + (iy - cursor[1]) ** 2
        if best_dist2 is None or dist2 < best_dist2:
            best_dist2 = dist2
            best_info = info
            best_tip = (ix, iy)
    return best_info["landmarks"], best_tip, best_info.get("label")


class PinchDetector:
    def __init__(
        self,
        on_ratio=PINCH_ON_RATIO,
        off_ratio=PINCH_OFF_RATIO,
        use_filter=USE_ONE_EURO,
        min_cutoff=ONE_EURO_PINCH_MIN_CUTOFF,
        beta=ONE_EURO_PINCH_BETA,
        d_cutoff=ONE_EURO_D_CUTOFF,
    ):
        if on_ratio <= 0 or off_ratio <= on_ratio:
            raise ValueError("Invalid pinch ratios: ensure 0 < on_ratio < off_ratio.")
        self._on_ratio = on_ratio
        self._off_ratio = off_ratio
        self._ratio_filter = OneEuroFilter(min_cutoff, beta, d_cutoff) if use_filter else None
        self._pinched = False

    def reset(self):
        self._pinched = False
        if self._ratio_filter is not None:
            self._ratio_filter.reset()

    def update(self, landmarks, dt=None):
        scale2 = _hand_scale2(landmarks)
        if scale2 <= 0:
            self._pinched = False
            return False, False
        ratio2 = _dist2(landmarks[4], landmarks[8]) / scale2
        ratio = math.sqrt(ratio2)
        if self._ratio_filter is not None and dt is not None:
            ratio = self._ratio_filter.apply(ratio, dt)

        if not self._pinched:
            if ratio < self._on_ratio:
                self._pinched = True
                return True, True
            return False, False

        if ratio > self._off_ratio:
            self._pinched = False
        return self._pinched, False


def main():
    args = get_args()

    landmarker = None
    mp_hands = None
    mp_draw = None
    hands = None
    if use_tasks_api:
        if not MODEL_PATH.exists():
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            try:
                print("Downloading hand landmarker model...")
                urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to download model from {MODEL_URL}. "
                    f"Download it manually and place at {MODEL_PATH}."
                ) from exc

        def _create_base_options():
            if not ENABLE_GPU:
                return mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH))
            try:
                return mp.tasks.BaseOptions(
                    model_asset_path=str(MODEL_PATH),
                    delegate=mp.tasks.BaseOptions.Delegate.GPU,
                )
            except Exception as exc:
                print(f"GPU delegate unavailable, falling back to CPU: {exc}")
                return mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH))

        base_options = _create_base_options()
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=args.max_num_hands,
            min_hand_detection_confidence=args.min_detection_confidence,
            min_hand_presence_confidence=MIN_PRESENCE_CONFIDENCE,
            min_tracking_confidence=args.min_tracking_confidence,
        )
        landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
    else:
        mp_hands = mp.solutions.hands
        mp_draw = mp.solutions.drawing_utils
        hands = mp_hands.Hands(
            static_image_mode=args.use_static_image_mode,
            max_num_hands=args.max_num_hands,
            min_detection_confidence=args.min_detection_confidence,
            min_tracking_confidence=args.min_tracking_confidence,
        )

    cap = cv.VideoCapture(args.device)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam.")
    cap.set(cv.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, args.height)
    start_time = time.perf_counter()

    serial_port = None
    if SERIAL_ENABLED and _use_serial():
        if serial is None:
            raise RuntimeError("pyserial is not installed. Install it or set SERIAL_ENABLED = False.")
        serial_port = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0)

    udp_socket = None
    if UDP_ENABLED and _use_udp():
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setblocking(False)

    btn_home = VirtualButton(20, 100, 150, 60, "RPS GAME")
    btn_mode = VirtualButton(20, 180, 150, 60, "MIMIC MODE")

    cursor_pos = None
    control_enabled = True
    pinch_active = False
    pinch_hold_start = None
    pinch_stable_emitted = False
    last_click_trigger_time = 0.0
    mimic_mode = False
    last_mimic_state = None
    last_serial_send = 0.0

    game_state = "idle"
    game_start_time = 0.0
    game_user_move = "NONE"
    game_robot_move = "NONE"
    game_result = "NONE"

    click_countdown_active = False
    click_countdown_start = 0.0
    click_target = None

    pinch_detector = PinchDetector()
    cursor_filter_x = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
    cursor_filter_y = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
    palm_filter_x = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
    palm_filter_y = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
    offset_filter_x = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
    offset_filter_y = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
    cursor_hist_x = deque(maxlen=CURSOR_MEDIAN_WINDOW)
    cursor_hist_y = deque(maxlen=CURSOR_MEDIAN_WINDOW)
    palm_hist_x = deque(maxlen=CURSOR_MEDIAN_WINDOW)
    palm_hist_y = deque(maxlen=CURSOR_MEDIAN_WINDOW)
    last_frame_time = time.perf_counter()

    while True:
        ret, image = cap.read()
        if not ret:
            break
        if FLIP_IMAGE:
            image = cv.flip(image, 1)
        debug_image = image
        image_rgb = cv.cvtColor(debug_image, cv.COLOR_BGR2RGB)
        image_rgb.flags.writeable = False

        h, w, _ = debug_image.shape
        now = time.perf_counter()
        dt = max(1e-6, now - last_frame_time)
        last_frame_time = now

        pinch_active = False
        just_pinched = False
        hands_info = []

        if use_tasks_api:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image_rgb)
            timestamp_ms = int((time.perf_counter() - start_time) * 1000)
            results = landmarker.detect_for_video(mp_image, timestamp_ms)
            if results.hand_landmarks:
                for idx, hand_landmarks in enumerate(results.hand_landmarks):
                    mp.tasks.vision.drawing_utils.draw_landmarks(
                        debug_image,
                        hand_landmarks,
                        mp.tasks.vision.HandLandmarksConnections.HAND_CONNECTIONS,
                    )
                    label = None
                    if hasattr(results, "handedness") and results.handedness and idx < len(results.handedness):
                        label = _label_from_classification_list(results.handedness[idx])
                    hands_info.append({"landmarks": hand_landmarks, "label": label})
        else:
            results = hands.process(image_rgb)
            if results.multi_hand_landmarks:
                for idx, hand_landmarks in enumerate(results.multi_hand_landmarks):
                    mp_draw.draw_landmarks(debug_image, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                    label = None
                    if results.multi_handedness and idx < len(results.multi_handedness):
                        label = _label_from_classification_list(results.multi_handedness[idx])
                    hands_info.append({"landmarks": hand_landmarks.landmark, "label": label})

        control_landmarks, index_tip, control_label = _select_control_hand(hands_info, cursor_pos, w, h)
        if control_landmarks is None:
            cursor_pos = None
            pinch_detector.reset()
            pinch_hold_start = None
            pinch_stable_emitted = False
            cursor_filter_x.reset()
            cursor_filter_y.reset()
            palm_filter_x.reset()
            palm_filter_y.reset()
            offset_filter_x.reset()
            offset_filter_y.reset()
            cursor_hist_x.clear()
            cursor_hist_y.clear()
            palm_hist_x.clear()
            palm_hist_y.clear()
        else:
            if game_state == "idle" and not mimic_mode:
                if _is_open_hand(control_landmarks):
                    control_enabled = True
                elif _is_fist(control_landmarks):
                    control_enabled = False

            pinch_allowed = control_enabled or mimic_mode or game_state != "idle"
            if pinch_allowed:
                pinch_active, just_pinched = pinch_detector.update(control_landmarks, dt)
            else:
                pinch_detector.reset()

            raw_x, raw_y = index_tip
            palm_x, palm_y = _palm_center_px(control_landmarks, w, h)
            if USE_CURSOR_MEDIAN:
                cursor_hist_x.append(raw_x)
                cursor_hist_y.append(raw_y)
                xs = sorted(cursor_hist_x)
                ys = sorted(cursor_hist_y)
                mid = len(xs) // 2
                raw_x = xs[mid]
                raw_y = ys[mid]
                palm_hist_x.append(palm_x)
                palm_hist_y.append(palm_y)
                pxs = sorted(palm_hist_x)
                pys = sorted(palm_hist_y)
                midp = len(pxs) // 2
                palm_x = pxs[midp]
                palm_y = pys[midp]

            if USE_PALM_ANCHOR:
                off_x = raw_x - palm_x
                off_y = raw_y - palm_y
                if USE_ONE_EURO:
                    spx = palm_filter_x.apply(palm_x, dt)
                    spy = palm_filter_y.apply(palm_y, dt)
                    sox = offset_filter_x.apply(off_x, dt)
                    soy = offset_filter_y.apply(off_y, dt)
                    new_x = int(spx + sox)
                    new_y = int(spy + soy)
                else:
                    new_x = palm_x + off_x
                    new_y = palm_y + off_y
            else:
                if USE_ONE_EURO:
                    fx = cursor_filter_x.apply(raw_x, dt)
                    fy = cursor_filter_y.apply(raw_y, dt)
                    new_x = int(fx)
                    new_y = int(fy)
                else:
                    if cursor_pos is None:
                        new_x, new_y = raw_x, raw_y
                    else:
                        new_x = int(cursor_pos[0] * (1 - CURSOR_SMOOTHING) + raw_x * CURSOR_SMOOTHING)
                        new_y = int(cursor_pos[1] * (1 - CURSOR_SMOOTHING) + raw_y * CURSOR_SMOOTHING)

            if cursor_pos is not None:
                dx = new_x - cursor_pos[0]
                dy = new_y - cursor_pos[1]
                if CURSOR_DEADZONE_PX > 0 and abs(dx) < CURSOR_DEADZONE_PX and abs(dy) < CURSOR_DEADZONE_PX:
                    new_x, new_y = cursor_pos
                else:
                    step = math.hypot(dx, dy)
                    max_step = CURSOR_MAX_STEP_PX
                    if CURSOR_MAX_STEP_RATIO > 0:
                        palm_w = _hand_scale_px(control_landmarks, w, h)
                        if palm_w > 0:
                            ratio_step = palm_w * CURSOR_MAX_STEP_RATIO
                            if max_step > 0:
                                max_step = min(max_step, ratio_step)
                            else:
                                max_step = ratio_step
                    if max_step > 0 and step > max_step:
                        scale = max_step / step
                        new_x = int(cursor_pos[0] + dx * scale)
                        new_y = int(cursor_pos[1] + dy * scale)

            cursor_pos = (new_x, new_y)

        stable_pinch = False
        if pinch_active:
            if pinch_hold_start is None:
                pinch_hold_start = now
            if (not pinch_stable_emitted) and (now - pinch_hold_start) >= PINCH_STABLE_SEC:
                pinch_stable_emitted = True
                stable_pinch = True
        else:
            pinch_hold_start = None
            pinch_stable_emitted = False

        btn_home.update(cursor_pos, pinch_active)
        btn_mode.update(cursor_pos, pinch_active)

        if (not click_countdown_active
                and stable_pinch
                and (now - last_click_trigger_time) >= CLICK_COOLDOWN_SEC):
            if btn_home.is_hovered:
                click_countdown_active = True
                click_countdown_start = now
                click_target = "home"
                last_click_trigger_time = now
            elif btn_mode.is_hovered:
                click_countdown_active = True
                click_countdown_start = now
                click_target = "mode"
                last_click_trigger_time = now

        if click_countdown_active:
            cancel_countdown = cursor_pos is None
            if click_target == "home" and not btn_home.is_hovered:
                cancel_countdown = True
            if click_target == "mode" and not btn_mode.is_hovered:
                cancel_countdown = True
            if not pinch_active:
                cancel_countdown = True

            if cancel_countdown:
                click_countdown_active = False
                click_target = None
            elif (now - click_countdown_start) >= CLICK_COUNTDOWN_SEC:
                if click_target == "home":
                    game_state = "countdown"
                    game_start_time = now
                    game_user_move = "NONE"
                    game_robot_move = "NONE"
                    game_result = "NONE"
                    if mimic_mode:
                        mimic_mode = False
                        _send_cmd("MIMIC:STOP", serial_port, udp_socket)
                    _send_cmd("MODE:GAME", serial_port, udp_socket)
                elif click_target == "mode":
                    mimic_mode = not mimic_mode
                    game_state = "idle"
                    game_user_move = "NONE"
                    game_robot_move = "NONE"
                    game_result = "NONE"
                    if mimic_mode:
                        _send_cmd("MODE:MIMIC", serial_port, udp_socket)
                    else:
                        _send_cmd("MIMIC:STOP", serial_port, udp_socket)
                        _send_cmd("MODE:IDLE", serial_port, udp_socket)
                click_countdown_active = False
                click_target = None

        if game_state == "countdown":
            remaining = GAME_COUNTDOWN_SEC - (now - game_start_time)
            if remaining <= 0 and game_user_move == "NONE":
                if control_landmarks is None:
                    user_move = "NONE"
                else:
                    user_move = _rps_from_landmarks(control_landmarks)
                    if user_move == "UNKNOWN":
                        user_move = "NONE"
                robot_move = random.choice(["ROCK", "PAPER", "SCISSORS"])
                game_user_move = user_move
                game_robot_move = robot_move
                game_result = _rps_winner(user_move, robot_move)
                _send_cmd(f"RPS:{robot_move}", serial_port, udp_socket)
                game_state = "reveal"
                game_start_time = now

        if game_state == "reveal":
            if (now - game_start_time) >= GAME_REVEAL_SEC:
                game_state = "idle"
                game_user_move = "NONE"
                game_robot_move = "NONE"
                game_result = "NONE"
                if not mimic_mode:
                    _send_cmd("MODE:IDLE", serial_port, udp_socket)

        if mimic_mode and game_state == "idle":
            right_hand = _find_hand_by_label(hands_info, MIMIC_HAND_LABEL)
            if right_hand is None and len(hands_info) == 1:
                right_hand = hands_info[0]["landmarks"]
            if right_hand is not None:
                states = _finger_states(right_hand)
                mimic_state = (
                    states["thumb"],
                    states["index"],
                    states["middle"],
                    states["ring"],
                )
                if mimic_state != last_mimic_state or (now - last_serial_send) >= SERIAL_SEND_INTERVAL:
                    cmd = f"MIMIC:{int(mimic_state[0])}{int(mimic_state[1])}{int(mimic_state[2])}{int(mimic_state[3])}"
                    _send_cmd(cmd, serial_port, udp_socket)
                    last_mimic_state = mimic_state
                    last_serial_send = now

        btn_home.draw(debug_image)
        btn_mode.draw(debug_image)

        if cursor_pos is not None:
            cursor_color = (0, 0, 255) if pinch_active else (0, 255, 0)
            cv.circle(debug_image, cursor_pos, 10, cursor_color, -1 if pinch_active else 2)
            if click_countdown_active:
                _draw_click_countdown(debug_image, cursor_pos, now - click_countdown_start, CLICK_COUNTDOWN_SEC)

        status = "ENABLED" if control_enabled else "PAUSED"
        cv.putText(debug_image, f"Control: {status}", (10, 30),
                   cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0) if control_enabled else (0, 0, 200), 2)
        if pinch_active:
            cv.putText(debug_image, "PINCH", (10, 60),
                       cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)
        if mimic_mode:
            cv.putText(debug_image, "MIMIC: ON", (10, 90),
                       cv.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 0), 2)
        if control_label:
            cv.putText(debug_image, f"Hand: {control_label}", (10, 120),
                       cv.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

        if game_state == "countdown":
            remaining = GAME_COUNTDOWN_SEC - (now - game_start_time)
            countdown_num = max(0, int(remaining) + 1)
            _draw_center_text(debug_image, str(countdown_num), int(h * 0.5), 3.0, (0, 255, 255), 5)
            _draw_center_text(debug_image, "Show gesture at 0", int(h * 0.5) + 60, 0.8, (255, 255, 255), 2)
        elif game_state == "reveal":
            _draw_center_text(debug_image, f"YOU: {game_user_move}", int(h * 0.45), 1.0, (255, 255, 255), 2)
            _draw_center_text(debug_image, f"ROBOT: {game_robot_move}", int(h * 0.52), 1.0, (255, 255, 255), 2)
            if game_result == "DRAW":
                result_text = "DRAW"
                result_color = (255, 255, 0)
            elif game_result == "USER":
                result_text = "YOU WIN"
                result_color = (0, 255, 0)
            else:
                result_text = "ROBOT WIN"
                result_color = (0, 0, 255)
            _draw_center_text(debug_image, result_text, int(h * 0.62), 1.2, result_color, 3)

        cv.imshow("Hand Tracking GUI (Demo Style)", debug_image)
        if cv.waitKey(1) & 0xFF == 27:
            break

    if use_tasks_api and landmarker is not None:
        landmarker.close()
    elif hands is not None:
        hands.close()
    if serial_port is not None:
        serial_port.close()
    if udp_socket is not None:
        udp_socket.close()
    cap.release()
    cv.destroyAllWindows()


if __name__ == "__main__":
    main()
