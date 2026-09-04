from pathlib import Path


# config.py:
# identity-verification/ai/face_verification/config.py
#
# parents:
# [0] face_verification
# [1] ai
# [2] identity-verification

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODELS_DIR = PROJECT_ROOT / "models"

YUNET_MODEL = (
    MODELS_DIR
    / "face_detection_yunet_2023mar.onnx"
)

SFACE_MODEL = (
    MODELS_DIR
    / "face_recognition_sface_2021dec.onnx"
)


# -------------------------
# Face detection
# -------------------------

FACE_DETECTION_THRESHOLD = 0.70
FACE_NMS_THRESHOLD = 0.30
FACE_TOP_K = 5000


# -------------------------
# Face verification
# -------------------------

SFACE_MATCH_THRESHOLD = 0.363

RECOMMENDED_MATCH_THRESHOLD = 0.40

# A decision is based on several quality-passed frames rather than whichever
# frame happened to arrive when liveness completed.
MIN_STABLE_EMBEDDING_SAMPLES = 3
MAX_STABLE_EMBEDDING_SAMPLES = 8
FACE_MATCH_UNCERTAINTY_MARGIN = 0.04


# -------------------------
# Quality
# -------------------------

MIN_FACE_WIDTH = 90
MIN_FACE_HEIGHT = 90

MIN_FACE_AREA_RATIO = 0.03

MIN_BLUR_SCORE = 10.0

MAX_FACE_AREA_RATIO = 0.65

MAX_CENTER_OFFSET_X = 0.25
MAX_CENTER_OFFSET_Y = 0.25


MIN_BRIGHTNESS = 45.0
MAX_BRIGHTNESS = 220.0


# -------------------------
# Liveness
# -------------------------

BLINK_CLOSED_EAR = 0.20
BLINK_OPEN_EAR = 0.23

# Browser capture is sampled over HTTP rather than at webcam frame rate. A
# natural blink may therefore be visible in only one analyzed frame. Requiring
# the eyes to reopen after that frame provides the second half of the signal.
MIN_CLOSED_FRAMES = 1
BLINK_CALIBRATION_FRAMES = 3
BLINK_CLOSED_RATIO = 0.72
BLINK_REOPEN_RATIO = 0.86

HEAD_TURN_THRESHOLD = 0.045
HEAD_CENTER_THRESHOLD = 0.055
LIVENESS_TIMEOUT_SECONDS = 45

HEAD_TURN_FRAMES = 2
HEAD_CENTER_FRAMES = 3
