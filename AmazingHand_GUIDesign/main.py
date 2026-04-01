import cv2
import mediapipe as mp
import time
import urllib.request
import random
import socket
import math
from collections import deque
from pathlib import Path

# Check if the current environment uses the newer Tasks API (MediaPipe 0.10+ / Python 3.13+)
# The older 'mp.solutions' API is deprecated in newer versions.
use_tasks_api = not hasattr(mp, "solutions")

try:
    import serial  # type: ignore
except Exception:
    serial = None

# Model URLs and local paths for the Tasks API hand landmarker model
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"

# ================= Runtime Tuning Parameters =================
ENABLE_GPU = False  # Try GPU delegate for Tasks API if available (may require specific hardware setups).
CAP_WIDTH = 960  # Match the demo resolution for more stable landmark output.
CAP_HEIGHT = 540
MAX_NUM_HANDS = 1  # Reduce hand switching/jitter (demo uses 1).
MIN_DETECTION_CONFIDENCE = 0.7
MIN_TRACKING_CONFIDENCE = 0.5
MIN_PRESENCE_CONFIDENCE = 0.5
USE_STATIC_IMAGE_MODE = False  # Solutions API only.
PINCH_ON_RATIO = 0.24  # Threshold to trigger a pinch (smaller = fingers must be closer).
PINCH_OFF_RATIO = 0.42  # Threshold to release a pinch. Must be > PINCH_ON_RATIO to create hysteresis (prevents flickering).
CURSOR_SMOOTHING = 0.7  # 0.0 = no smoothing (jittery), 0.99 = maximum smoothing (laggy).
THUMB_OPEN_RATIO = 0.32  # Threshold for thumb extension. Larger = thumb must be farther from palm to count as open.
GAME_COUNTDOWN_SEC = 3.0  # Duration of the Rock-Paper-Scissors countdown.
GAME_REVEAL_SEC = 2.0  # How long the Rock-Paper-Scissors result stays on screen.
CLICK_COUNTDOWN_SEC = 3.0  # Delay before executing a GUI click action.
PINCH_STABLE_SEC = 0.12  # Pinch must be held this long to count as a valid click trigger.
CLICK_COOLDOWN_SEC = 0.5  # Minimum time between click triggers to avoid rapid repeats.
USE_ONE_EURO = True  # Enable One Euro filter for smoother cursor/pinch without big lag.
ONE_EURO_MIN_CUTOFF = 1.6  # Lower = smoother, higher = more responsive.
ONE_EURO_BETA = 0.015  # Higher = less lag during fast motion.
ONE_EURO_D_CUTOFF = 1.0  # Derivative cutoff for One Euro filter.
ONE_EURO_PINCH_MIN_CUTOFF = 2.0  # Pinch ratio smoothing baseline.
ONE_EURO_PINCH_BETA = 0.01  # Pinch ratio responsiveness.
USE_CURSOR_MEDIAN = True  # Median filter for cursor to suppress jitter spikes.
CURSOR_MEDIAN_WINDOW = 5  # Number of frames for median filter (odd number recommended).
CURSOR_DEADZONE_PX = 2  # Ignore tiny movements smaller than this (in pixels).
CURSOR_MAX_STEP_PX = 24  # Clamp per-frame movement to avoid sudden jumps.
CURSOR_MAX_STEP_RATIO = 0.7  # Clamp per-frame movement based on palm width (0 to disable).
USE_PALM_ANCHOR = True  # Stabilize cursor by smoothing palm center + finger offset.
FLIP_IMAGE = True  # Mirror the webcam feed (highly recommended for intuitive hand control).
MIMIC_HAND_LABEL = "Left" if FLIP_IMAGE else "Right"  # Determines which hand acts as the master in Mimic mode.

# ================= Transport Configuration (ESP32) =================
CONTROL_TRANSPORT = "udp"  # Options: "serial" | "udp" | "both"
SERIAL_ENABLED = False
SERIAL_PORT = "COM3"
SERIAL_BAUD = 115200
SERIAL_SEND_INTERVAL = 0.08  # Limit how fast commands are sent to avoid overwhelming the ESP32 (e.g., 0.08s = ~12.5 Hz).
SERIAL_LOG = True  # Print commands to the console for debugging even if transport is disabled.

UDP_ENABLED = True
UDP_IP = "192.168.1.50"  # The IP address of your ESP32 on the local Wi-Fi network.
UDP_PORT = 6000  # The port your ESP32 is listening to.
WEBCAMID =1

# ================= MediaPipe Initialization =================
if use_tasks_api:
    # Ensure the task model file exists locally; download it if it doesn't.
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
        """Configure Tasks API options, falling back to CPU if GPU delegate fails."""
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
        num_hands=MAX_NUM_HANDS,
        min_hand_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_hand_presence_confidence=MIN_PRESENCE_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE,
    )
    landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
else:
    # Fallback to the older Solutions API for older Python/MediaPipe versions.
    mp_hands = mp.solutions.hands
    mp_draw = mp.solutions.drawing_utils

    hands = mp_hands.Hands(
        static_image_mode=USE_STATIC_IMAGE_MODE,
        max_num_hands=MAX_NUM_HANDS,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence=MIN_TRACKING_CONFIDENCE
    )


def _use_serial():
    """Helper to check if Serial transport is requested."""
    return CONTROL_TRANSPORT in ("serial", "both")


def _use_udp():
    """Helper to check if UDP transport is requested."""
    return CONTROL_TRANSPORT in ("udp", "both")


# Initialize Serial Port
serial_port = None
if SERIAL_ENABLED and _use_serial():
    if serial is None:
        raise RuntimeError("pyserial is not installed. Install it or set SERIAL_ENABLED = False.")
    try:
        serial_port = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0)
        print(f"Serial opened: {SERIAL_PORT} @ {SERIAL_BAUD}")
    except Exception as exc:
        raise RuntimeError(f"Failed to open serial port {SERIAL_PORT}: {exc}") from exc

# Initialize UDP Socket
udp_socket = None
if UDP_ENABLED and _use_udp():
    try:
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setblocking(False)  # Non-blocking to prevent UI lag
        print(f"UDP ready: {UDP_IP}:{UDP_PORT}")
    except Exception as exc:
        raise RuntimeError(f"Failed to init UDP socket: {exc}") from exc


# ================= Virtual Button Class =================
class VirtualButton:
    """A GUI component that detects 'pinch' clicks inside a designated rectangular area."""

    def __init__(self, x, y, w, h, text):
        self.rect = (x, y, w, h)
        self.text = text
        self.is_hovered = False
        self.is_clicked = False
        self.color_normal = (150, 50, 50)  # Default color (BGR: Dark Blue)
        self.color_hover = (255, 150, 0)  # Hover color (BGR: Light Blue)
        self.color_click = (0, 200, 0)  # Click color (BGR: Green)
        self.text_color = (255, 255, 255)  # Text color (White)

    def update(self, cursor, is_pinch, just_pinched):
        """Updates button state. Returns True exactly once per physical click (debounce)."""
        if cursor is None:
            self.is_hovered = False
            self.is_clicked = False
            return False

        cx, cy = cursor
        x, y, w, h = self.rect

        # Check intersection between cursor coordinate and button bounding box
        self.is_hovered = (x <= cx <= x + w) and (y <= cy <= y + h)

        # Trigger click only on hover and at the exact moment of a "just pinched" action
        if self.is_hovered and just_pinched:
            self.is_clicked = True
            return True

        # Reset visual click state when pinch is released
        if not is_pinch:
            self.is_clicked = False

        return False

    def draw(self, img):
        """Draws the background, border, and centered text of the button."""
        x, y, w, h = self.rect

        if self.is_clicked:
            bg_color = self.color_click
        elif self.is_hovered:
            bg_color = self.color_hover
        else:
            bg_color = self.color_normal

        cv2.rectangle(img, (x, y), (x + w, y + h), bg_color, -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 255, 255), 2)

        text_size = cv2.getTextSize(self.text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
        text_x = x + (w - text_size[0]) // 2
        text_y = y + (h + text_size[1]) // 2
        cv2.putText(img, self.text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, self.text_color, 2)


# ================= Communication & Drawing Helpers =================
def _send_cmd(cmd):
    """Dispatches command strings via Serial, UDP, or both depending on configuration."""
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
    """Utility to draw perfectly horizontally centered text on the screen."""
    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0]
    x = (img.shape[1] - text_size[0]) // 2
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


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
    """
    One Euro Filter for real-time smoothing with low lag.
    Reference: http://cristal.univ-lille.fr/~casiez/1euro/
    """

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


def _draw_click_countdown(img, cursor, elapsed, duration):
    """Draws a Windows-style dwell countdown ring around the cursor."""
    if cursor is None or duration <= 0:
        return
    progress = min(1.0, max(0.0, elapsed / duration))
    radius = 22
    thickness = 3
    base_color = (210, 210, 210)
    arc_color = (255, 255, 255)

    cv2.circle(img, cursor, radius, base_color, 1)
    start_angle = -90
    end_angle = start_angle + (progress * 360.0)
    cv2.ellipse(img, cursor, (radius, radius), 0, start_angle, end_angle, arc_color, thickness)


# ================= OpenCV Webcam Initialization =================
cap = cv2.VideoCapture(WEBCAMID)
if not cap.isOpened():
    raise RuntimeError("Could not open webcam (index 0).")
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_HEIGHT)
start_time = time.perf_counter()

# State variables
cursor_pos = None
cursor_smoothing = CURSOR_SMOOTHING
control_enabled = True
pinch_active = False
pinch_hold_start = None
pinch_stable_emitted = False
last_click_trigger_time = 0.0
mimic_mode = False
last_mimic_state = None
last_serial_send = 0.0
last_frame_time = time.perf_counter()

cursor_filter_x = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
cursor_filter_y = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
cursor_hist_x = deque(maxlen=CURSOR_MEDIAN_WINDOW)
cursor_hist_y = deque(maxlen=CURSOR_MEDIAN_WINDOW)
palm_filter_x = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
palm_filter_y = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
offset_filter_x = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
offset_filter_y = OneEuroFilter(ONE_EURO_MIN_CUTOFF, ONE_EURO_BETA, ONE_EURO_D_CUTOFF)
palm_hist_x = deque(maxlen=CURSOR_MEDIAN_WINDOW)
palm_hist_y = deque(maxlen=CURSOR_MEDIAN_WINDOW)

# RPS Game state machine variables
game_state = "idle"  # States: "idle", "countdown", "reveal"
game_start_time = 0.0
game_user_move = "NONE"
game_robot_move = "NONE"
game_result = "NONE"

# Click countdown state
click_countdown_active = False
click_countdown_start = 0.0
click_target = None

# Instantiate UI buttons
btn_home = VirtualButton(20, 100, 150, 60, "RPS GAME")
btn_mode = VirtualButton(20, 180, 150, 60, "MIMIC MODE")


# ================= Core Math & Gesture Helpers =================
def _to_pixel(lm, w, h):
    """Converts normalized landmark coordinates (0.0 to 1.0) into absolute pixel coordinates."""
    return int(lm.x * w), int(lm.y * h)


def _dist2(a, b):
    """Calculates squared Euclidean distance between two landmarks (skips expensive sqrt operation)."""
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy


def _label_from_classification_list(classification_list):
    """Safely extracts 'Left' or 'Right' hand label from MediaPipe's complex nested output."""
    if classification_list is None:
        return None
    if hasattr(classification_list, "classification"):
        classification_list = classification_list.classification
    if not classification_list:
        return None
    first = classification_list[0]
    return getattr(first, "category_name", None) or getattr(first, "label", None)


def _is_open_hand(landmarks):
    """Heuristic: Considers hand open if at least 3 fingertips are above their PIP joints."""
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    extended = sum(1 for tip_i, pip_i in zip(tips, pips) if landmarks[tip_i].y < landmarks[pip_i].y)
    return extended >= 3


def _is_fist(landmarks):
    """Heuristic: Considers hand a fist if at least 3 fingertips are curled below their PIP joints."""
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    curled = sum(1 for tip_i, pip_i in zip(tips, pips) if landmarks[tip_i].y > landmarks[pip_i].y)
    return curled >= 3


def _hand_scale2(landmarks):
    """Calculates palm width squared. Used as a reference scale to normalize distances so gestures work at any depth."""
    return _dist2(landmarks[5], landmarks[17])


def _hand_scale_px(landmarks, w, h):
    """Calculates palm width in pixels for dynamic cursor clamping."""
    x1, y1 = _to_pixel(landmarks[5], w, h)
    x2, y2 = _to_pixel(landmarks[17], w, h)
    return math.hypot(x1 - x2, y1 - y2)


def _palm_center_px(landmarks, w, h):
    """Calculates palm center in pixels using stable palm landmarks."""
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
    """Checks if thumb is extended by comparing its distance from the index base against the palm scale."""
    scale2 = _hand_scale2(landmarks)
    if scale2 <= 0:
        return False
    ratio2 = _dist2(landmarks[4], landmarks[5]) / scale2
    return ratio2 > (THUMB_OPEN_RATIO * THUMB_OPEN_RATIO)


def _finger_states(landmarks):
    """Returns a dictionary mapping each finger to a boolean indicating if it is fully extended."""
    return {
        "thumb": _thumb_open(landmarks),
        "index": landmarks[8].y < landmarks[6].y,
        "middle": landmarks[12].y < landmarks[10].y,
        "ring": landmarks[16].y < landmarks[14].y,
        "pinky": landmarks[20].y < landmarks[18].y,
    }


def _rps_from_landmarks(landmarks):
    """Evaluates finger extensions to classify a gesture as Rock, Paper, or Scissors."""
    states = _finger_states(landmarks)
    extended = [states["index"], states["middle"], states["ring"], states["pinky"]]
    extended_count = sum(1 for v in extended if v)

    if extended_count <= 1:
        return "ROCK"  # Mostly closed
    if states["index"] and states["middle"] and not states["ring"] and not states["pinky"]:
        return "SCISSORS"  # Only index and middle extended (V-sign)
    if extended_count >= 3:
        return "PAPER"  # Mostly open
    return "UNKNOWN"


def _rps_winner(user_move, robot_move):
    """Determines the winner of a Rock-Paper-Scissors match."""
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
    """Finds the landmarks of a specific hand ('Left' or 'Right') from the detected hands list."""
    for info in hands:
        if info.get("label") == label:
            return info.get("landmarks")
    return None


class PinchDetector:
    """
    Detects thumb-index pinch gestures using Hysteresis.
    Hysteresis requires the fingers to move closer to trigger a pinch (ON_RATIO),
    but allows them to drift slightly further apart before releasing the pinch (OFF_RATIO).
    This prevents the pinch state from rapidly flickering when hovering near the threshold.
    """

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
        """Processes landmarks. Returns a tuple: (is_currently_pinching, just_pinched_this_frame)"""
        scale2 = _hand_scale2(landmarks)
        if scale2 <= 0:
            self._pinched = False
            return False, False

        # Calculate squared distance between thumb tip and index tip, normalized by hand scale
        ratio2 = _dist2(landmarks[4], landmarks[8]) / scale2
        ratio = math.sqrt(ratio2)
        if self._ratio_filter is not None and dt is not None:
            ratio = self._ratio_filter.apply(ratio, dt)

        if not self._pinched:
            # If not pinching, ratio must cross the tighter ON threshold to trigger
            if ratio < self._on_ratio:
                self._pinched = True
                return True, True
            return False, False

        # If already pinching, ratio must cross the looser OFF threshold to release
        if ratio > self._off_ratio:
            self._pinched = False
        return self._pinched, False


def _select_control_hand(hands, cursor, w, h):
    """
    Determines which hand controls the cursor.
    If multiple hands are present, it selects the hand closest to the current cursor position
    to prevent the cursor from instantly jumping to the other hand.
    """
    if not hands:
        return None, None, None

    # If no cursor exists yet, just pick the first hand detected
    if cursor is None:
        info = hands[0]
        landmarks = info["landmarks"]
        return landmarks, _to_pixel(landmarks[8], w, h), info.get("label")

    best_info = None
    best_tip = None
    best_dist2 = None
    # Iterate through detected hands to find the one closest to current cursor
    for info in hands:
        landmarks = info["landmarks"]
        ix, iy = _to_pixel(landmarks[8], w, h)
        dist2 = (ix - cursor[0]) ** 2 + (iy - cursor[1]) ** 2
        if best_dist2 is None or dist2 < best_dist2:
            best_dist2 = dist2
            best_info = info
            best_tip = (ix, iy)

    return best_info["landmarks"], best_tip, best_info.get("label")


# ============================================

pinch_detector = PinchDetector()

# Main processing loop
while True:
    success, img = cap.read()
    if not success:
        break

    if FLIP_IMAGE:
        img = cv2.flip(img, 1)
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_rgb.flags.writeable = False
    h, w, _ = img.shape
    now = time.perf_counter()
    dt = max(1e-6, now - last_frame_time)
    last_frame_time = now

    # Reset pinch state every frame; True only if hand is detected and pinching
    pinch_active = False
    just_pinched = False
    hands_info = []

    # Process image with MediaPipe
    if use_tasks_api:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        timestamp_ms = int((time.perf_counter() - start_time) * 1000)
        results = landmarker.detect_for_video(mp_image, timestamp_ms)

        if results.hand_landmarks:
            for idx, hand_landmarks in enumerate(results.hand_landmarks):
                mp.tasks.vision.drawing_utils.draw_landmarks(
                    img,
                    hand_landmarks,
                    mp.tasks.vision.HandLandmarksConnections.HAND_CONNECTIONS,
                )
                label = None
                if hasattr(results, "handedness") and results.handedness and idx < len(results.handedness):
                    label = _label_from_classification_list(results.handedness[idx])
                hands_info.append({"landmarks": hand_landmarks, "label": label})
    else:
        results = hands.process(img_rgb)
        if results.multi_hand_landmarks:
            for idx, hand_landmarks in enumerate(results.multi_hand_landmarks):
                mp_draw.draw_landmarks(
                    img,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS
                )
                label = None
                if results.multi_handedness and idx < len(results.multi_handedness):
                    handedness = results.multi_handedness[idx]
                    classification_list = getattr(handedness, "classification", None)
                    if classification_list is None:
                        classification_list = handedness
                    label = _label_from_classification_list(classification_list)
                hands_info.append({"landmarks": hand_landmarks.landmark, "label": label})

    # Find the hand controlling the UI
    control_landmarks, index_tip, control_label = _select_control_hand(hands_info, cursor_pos, w, h)

    if control_landmarks is None:
        cursor_pos = None
        pinch_detector.reset()
        pinch_hold_start = None
        pinch_stable_emitted = False
        cursor_filter_x.reset()
        cursor_filter_y.reset()
        cursor_hist_x.clear()
        cursor_hist_y.clear()
        palm_filter_x.reset()
        palm_filter_y.reset()
        offset_filter_x.reset()
        offset_filter_y.reset()
        palm_hist_x.clear()
        palm_hist_y.clear()
    else:
        # Check open/closed palm to pause/resume control (only in idle mode)
        if game_state == "idle" and not mimic_mode:
            if _is_open_hand(control_landmarks):
                control_enabled = True
            elif _is_fist(control_landmarks):
                control_enabled = False

        # Allow pinching if control is enabled, or if we are actively playing a game or mimicking
        pinch_allowed = control_enabled or mimic_mode or game_state != "idle"
        if pinch_allowed:
            pinch_active, just_pinched = pinch_detector.update(control_landmarks, dt)
        else:
            pinch_detector.reset()

        # Update cursor position using One Euro filter or exponential moving average (smoothing)
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
                    new_x = int(cursor_pos[0] * (1 - cursor_smoothing) + raw_x * cursor_smoothing)
                    new_y = int(cursor_pos[1] * (1 - cursor_smoothing) + raw_y * cursor_smoothing)

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

    # Pinch stability filtering (reduces jitter-triggered clicks)
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

    # ================= GUI Update & Logic =================

    # Update button hover states (click is handled via countdown)
    btn_home.update(cursor_pos, pinch_active, False)
    btn_mode.update(cursor_pos, pinch_active, False)

    # Start click countdown on stable pinch (with cooldown)
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

    # Handle click countdown progression
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
                    _send_cmd("MIMIC:STOP")
                _send_cmd("MODE:GAME")
            elif click_target == "mode":
                mimic_mode = not mimic_mode
                game_state = "idle"
                game_user_move = "NONE"
                game_robot_move = "NONE"
                game_result = "NONE"
                if mimic_mode:
                    _send_cmd("MODE:MIMIC")
                else:
                    _send_cmd("MIMIC:STOP")
                    _send_cmd("MODE:IDLE")
            click_countdown_active = False
            click_target = None

    # State Machine: RPS GAME COUNTDOWN
    if game_state == "countdown":
        remaining = GAME_COUNTDOWN_SEC - (now - game_start_time)
        if remaining <= 0 and game_user_move == "NONE":
            # Time's up! Capture user gesture
            if control_landmarks is None:
                user_move = "NONE"
            else:
                user_move = _rps_from_landmarks(control_landmarks)
                if user_move == "UNKNOWN":
                    user_move = "NONE"

            # Robot makes a random choice
            robot_move = random.choice(["ROCK", "PAPER", "SCISSORS"])
            game_user_move = user_move
            game_robot_move = robot_move
            game_result = _rps_winner(user_move, robot_move)

            # Send robot's move to ESP32 to actuate
            _send_cmd(f"RPS:{robot_move}")

            # Transition to reveal state
            game_state = "reveal"
            game_start_time = now

    # State Machine: RPS GAME REVEAL
    if game_state == "reveal":
        # Wait a few seconds to show the result, then return to idle
        if (now - game_start_time) >= GAME_REVEAL_SEC:
            game_state = "idle"
            game_user_move = "NONE"
            game_robot_move = "NONE"
            game_result = "NONE"
            if not mimic_mode:
                _send_cmd("MODE:IDLE")

    # Logic: MIMIC MODE Execution
    if mimic_mode and game_state == "idle":
        right_hand = _find_hand_by_label(hands_info, MIMIC_HAND_LABEL)
        # Fallback if only one hand is visible and label is incorrect
        if right_hand is None and len(hands_info) == 1:
            right_hand = hands_info[0]["landmarks"]

        if right_hand is not None:
            states = _finger_states(right_hand)
            # Create a 4-bit representation of finger states (thumb, index, middle, ring)
            mimic_state = (
                states["thumb"],
                states["index"],
                states["middle"],
                states["ring"],
            )
            # Send data only if state changed OR interval time has passed (to keep robot updated)
            if mimic_state != last_mimic_state or (now - last_serial_send) >= SERIAL_SEND_INTERVAL:
                cmd = f"MIMIC:{int(mimic_state[0])}{int(mimic_state[1])}{int(mimic_state[2])}{int(mimic_state[3])}"
                _send_cmd(cmd)
                last_mimic_state = mimic_state
                last_serial_send = now

    # ================= UI Rendering =================
    # Draw buttons
    btn_home.draw(img)
    btn_mode.draw(img)

    # Draw cursor (green outline when hovering, solid red when pinching)
    if cursor_pos is not None:
        cursor_color = (0, 0, 255) if pinch_active else (0, 255, 0)  # BGR
        cv2.circle(img, cursor_pos, 10, cursor_color, -1 if pinch_active else 2)
        if click_countdown_active:
            _draw_click_countdown(img, cursor_pos, now - click_countdown_start, CLICK_COUNTDOWN_SEC)

    # Draw top-left status texts
    status = "ENABLED" if control_enabled else "PAUSED"
    cv2.putText(img, f"Control: {status}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0) if control_enabled else (0, 0, 200), 2)
    if pinch_active:
        cv2.putText(img, "PINCH", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)

    if mimic_mode:
        cv2.putText(img, "MIMIC: ON", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 0), 2)
    if control_label:
        cv2.putText(img, f"Hand: {control_label}", (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

    # Draw Game UI elements
    if game_state == "countdown":
        remaining = GAME_COUNTDOWN_SEC - (now - game_start_time)
        countdown_num = max(0, int(remaining) + 1)
        _draw_center_text(img, str(countdown_num), int(h * 0.5), 3.0, (0, 255, 255), 5)
        _draw_center_text(img, "Show gesture at 0", int(h * 0.5) + 60, 0.8, (255, 255, 255), 2)
    elif game_state == "reveal":
        _draw_center_text(img, f"YOU: {game_user_move}", int(h * 0.45), 1.0, (255, 255, 255), 2)
        _draw_center_text(img, f"ROBOT: {game_robot_move}", int(h * 0.52), 1.0, (255, 255, 255), 2)
        if game_result == "DRAW":
            result_text = "DRAW"
            result_color = (255, 255, 0)
        elif game_result == "USER":
            result_text = "YOU WIN"
            result_color = (0, 255, 0)
        else:
            result_text = "ROBOT WIN"
            result_color = (0, 0, 255)
        _draw_center_text(img, result_text, int(h * 0.62), 1.2, result_color, 3)
    # ==================================================

    cv2.imshow("Hand Tracking GUI", img)

    if cv2.waitKey(1) & 0xFF == 27:  # Press ESC to exit
        break

# Cleanup resources
if use_tasks_api:
    landmarker.close()

if serial_port is not None:
    serial_port.close()
if udp_socket is not None:
    udp_socket.close()

cap.release()
cv2.destroyAllWindows()
