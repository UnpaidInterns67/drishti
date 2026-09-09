from __future__ import annotations

import secrets
import time

import mediapipe as mp
import numpy as np

from .config import (
    BLINK_CALIBRATION_FRAMES,
    BLINK_CLOSED_EAR,
    BLINK_CLOSED_RATIO,
    BLINK_OPEN_EAR,
    BLINK_REOPEN_RATIO,
    HEAD_CENTER_FRAMES,
    HEAD_CENTER_THRESHOLD,
    HEAD_TURN_FRAMES,
    HEAD_TURN_THRESHOLD,
    LIVENESS_TIMEOUT_SECONDS,
    MIN_CLOSED_FRAMES,
)
from .utils import euclidean_distance


class LivenessDetector:
    LEFT_EYE = [362, 385, 387, 263, 373, 380]
    RIGHT_EYE = [33, 160, 158, 133, 153, 144]

    NOSE_TIP = 1
    LEFT_CHEEK = 234
    RIGHT_CHEEK = 454

    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh

        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        self.reset()

    def reset(self):
        self.started_at = time.time()

        self.state = "BLINK"

        self.closed_frames = 0
        self.blink_detected = False
        self.blink_ready = False
        self.open_ear_baseline = None
        self._blink_calibration = []

        self.turn_frames = 0
        self.head_turn_detected = False
        self.turn_direction = None
        self.required_turn_direction = secrets.choice(("LEFT", "RIGHT"))

        self.center_frames = 0
        self.returned_center = False

        self.latest_ear = None
        self.latest_yaw_signal = None
        self.center_yaw_baseline = None
        self._center_yaw_samples = []

    def close(self):
        self.face_mesh.close()

    @staticmethod
    def _point(landmarks, index, width, height):
        landmark = landmarks[index]

        return np.array(
            [
                landmark.x * width,
                landmark.y * height,
            ],
            dtype=np.float32,
        )

    def _eye_aspect_ratio(
        self,
        landmarks,
        indices,
        width,
        height,
    ) -> float:
        p1 = self._point(landmarks, indices[0], width, height)
        p2 = self._point(landmarks, indices[1], width, height)
        p3 = self._point(landmarks, indices[2], width, height)
        p4 = self._point(landmarks, indices[3], width, height)
        p5 = self._point(landmarks, indices[4], width, height)
        p6 = self._point(landmarks, indices[5], width, height)

        vertical_1 = euclidean_distance(p2, p6)
        vertical_2 = euclidean_distance(p3, p5)

        horizontal = euclidean_distance(p1, p4)

        if horizontal <= 1e-6:
            return 0.0

        ear = (
            vertical_1 + vertical_2
        ) / (2.0 * horizontal)

        return float(ear)

    def _average_ear(
        self,
        landmarks,
        width,
        height,
    ) -> float:
        left = self._eye_aspect_ratio(
            landmarks,
            self.LEFT_EYE,
            width,
            height,
        )

        right = self._eye_aspect_ratio(
            landmarks,
            self.RIGHT_EYE,
            width,
            height,
        )

        return (left + right) / 2.0

    def _yaw_signal(
        self,
        landmarks,
        width,
        height,
    ) -> float:
        nose = self._point(
            landmarks,
            self.NOSE_TIP,
            width,
            height,
        )

        cheek_a = self._point(
            landmarks,
            self.LEFT_CHEEK,
            width,
            height,
        )

        cheek_b = self._point(
            landmarks,
            self.RIGHT_CHEEK,
            width,
            height,
        )

        left_x = min(cheek_a[0], cheek_b[0])
        right_x = max(cheek_a[0], cheek_b[0])

        face_width = right_x - left_x

        if face_width <= 1e-6:
            return 0.0

        nose_ratio = (nose[0] - left_x) / face_width

        return float(nose_ratio - 0.5)

    def process(self, frame_rgb: np.ndarray) -> dict:
        elapsed = time.time() - self.started_at

        if self.state != "PASSED" and elapsed > LIVENESS_TIMEOUT_SECONDS:
            return {
                "passed": False,
                "failed": True,
                "reason": "timeout",
                "state": self.state,
                "score": self.score(),
            }

        height, width = frame_rgb.shape[:2]

        result = self.face_mesh.process(frame_rgb)

        if not result.multi_face_landmarks:
            return {
                "passed": False,
                "failed": False,
                "reason": "face_landmarks_not_found",
                "state": self.state,
                "instruction": self.instruction(),
                "score": self.score(),
            }

        landmarks = (
            result.multi_face_landmarks[0].landmark
        )

        ear = self._average_ear(
            landmarks,
            width,
            height,
        )

        yaw_signal = self._yaw_signal(
            landmarks,
            width,
            height,
        )

        self.latest_ear = ear
        self.latest_yaw_signal = yaw_signal

        # Learn the user's neutral pose while blink calibration/challenge is
        # running. Absolute face geometry varies enough to make a fixed zero
        # center unreliable across cameras and people.
        if self.state == "BLINK" and np.isfinite(yaw_signal):
            self._center_yaw_samples.append(float(yaw_signal))
            self._center_yaw_samples = self._center_yaw_samples[-12:]
            self.center_yaw_baseline = float(np.median(self._center_yaw_samples))

        relative_yaw = yaw_signal - (self.center_yaw_baseline or 0.0)

        if self.state == "BLINK":
            if self.blink_ready:
                self._process_blink(ear)
            else:
                self._calibrate_blink(ear)

        elif self.state == "TURN_HEAD":
            self._process_head_turn(relative_yaw)

        elif self.state == "RETURN_CENTER":
            self._process_return_center(relative_yaw)

        passed = self.state == "PASSED"

        return {
            "passed": passed,
            "failed": False,
            "state": self.state,
            "instruction": self.instruction(),
            "blink_detected": self.blink_detected,
            "blink_ready": self.blink_ready,
            "blink_progress": self.closed_frames,
            "head_turn_detected": self.head_turn_detected,
            "returned_center": self.returned_center,
            "ear": round(ear, 4),
            "yaw_signal": round(yaw_signal, 4),
            "relative_yaw": round(relative_yaw, 4),
            "turn_progress": self.turn_frames,
            "turn_required": HEAD_TURN_FRAMES,
            "turn_direction": self.turn_direction,
            "required_turn_direction": self.required_turn_direction,
            "score": self.score(),
            "elapsed_seconds": round(elapsed, 2),
        }

    def _process_blink(self, ear: float):
        if self.open_ear_baseline is None:
            closed_threshold = BLINK_CLOSED_EAR
            reopen_threshold = BLINK_OPEN_EAR
        else:
            closed_threshold = max(
                0.12,
                min(0.22, self.open_ear_baseline * BLINK_CLOSED_RATIO),
            )
            reopen_threshold = max(
                closed_threshold + 0.02,
                self.open_ear_baseline * BLINK_REOPEN_RATIO,
            )

        if ear <= closed_threshold:
            self.closed_frames += 1

        elif (
            self.closed_frames >= MIN_CLOSED_FRAMES
            and ear >= reopen_threshold
        ):
            self.blink_detected = True
            self.closed_frames = 0
            self.state = "TURN_HEAD"

        elif ear >= reopen_threshold:
            self.closed_frames = 0

            # Slowly follow the user's normal open-eye geometry without
            # letting a single outlier redefine the baseline.
            if self.open_ear_baseline is not None:
                self.open_ear_baseline = (
                    self.open_ear_baseline * 0.9 + ear * 0.1
                )

    def _calibrate_blink(self, ear: float):
        """Learn this user's open-eye EAR before accepting a blink."""
        if not np.isfinite(ear) or ear <= 0.05:
            self._blink_calibration.clear()
            return

        self._blink_calibration.append(float(ear))
        if len(self._blink_calibration) < BLINK_CALIBRATION_FRAMES:
            return

        # The maximum is intentional: if the user blinks during calibration,
        # the subsequent open-eye sample still establishes a useful baseline.
        self.open_ear_baseline = max(self._blink_calibration)
        self._blink_calibration.clear()
        self.blink_ready = True

    def _process_head_turn(self, yaw_signal: float):
        direction = "LEFT" if yaw_signal < 0 else "RIGHT"

        if (
            abs(yaw_signal) >= HEAD_TURN_THRESHOLD
            and direction == self.required_turn_direction
        ):
            self.turn_frames += 1

            if self.turn_frames >= HEAD_TURN_FRAMES:
                self.head_turn_detected = True
                self.turn_direction = direction
                self.state = "RETURN_CENTER"
                self.turn_frames = 0
        else:
            # A detector miss or threshold-edge sample on a slow network must
            # not erase all correctly observed progress. Sustained wrong-way
            # movement still drains the counter and can never pass.
            self.turn_frames = max(0, self.turn_frames - 1)

    def _process_return_center(
        self,
        yaw_signal: float,
    ):
        if abs(yaw_signal) <= HEAD_CENTER_THRESHOLD:
            self.center_frames += 1

            if self.center_frames >= HEAD_CENTER_FRAMES:
                self.returned_center = True
                self.state = "PASSED"
        else:
            self.center_frames = 0

    def instruction(self) -> str:
        if self.state == "BLINK" and not self.blink_ready:
            return "Look at the camera and keep your eyes open"

        instructions = {
            "BLINK": "Blink once",
            "TURN_HEAD": (
                f"Turn your head {self.required_turn_direction.lower()}"
            ),
            "RETURN_CENTER": "Look straight at the camera",
            "PASSED": "Liveness passed",
        }

        return instructions.get(
            self.state,
            "Look at the camera",
        )

    def score(self) -> float:
        score = 0.0

        if self.blink_detected:
            score += 0.45

        if self.head_turn_detected:
            score += 0.35

        if self.returned_center:
            score += 0.20

        return round(score, 3)
