from __future__ import annotations

import cv2
import numpy as np

from .config import (
    MAX_BRIGHTNESS,
    MAX_CENTER_OFFSET_X,
    MAX_CENTER_OFFSET_Y,
    MAX_FACE_AREA_RATIO,
    MIN_BLUR_SCORE,
    MIN_BRIGHTNESS,
    MIN_FACE_AREA_RATIO,
    MIN_FACE_HEIGHT,
    MIN_FACE_WIDTH,
)


class FaceQualityChecker:
    def evaluate(self, frame: np.ndarray, face) -> dict:
        frame_height, frame_width = frame.shape[:2]

        x, y, w, h = [float(v) for v in face[:4]]

        frame_area = frame_width * frame_height
        face_area = w * h

        face_area_ratio = (
            face_area / frame_area if frame_area > 0 else 0.0
        )

        face_center_x = x + w / 2
        face_center_y = y + h / 2

        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2

        offset_x = abs(face_center_x - frame_center_x) / frame_width
        offset_y = abs(face_center_y - frame_center_y) / frame_height

        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(frame_width, int(x + w))
        y2 = min(frame_height, int(y + h))

        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            return {
                "passed": False,
                "reason": "invalid_face_crop",
            }

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        blur_score = float(
            cv2.Laplacian(gray, cv2.CV_64F).var()
        )

        brightness = float(np.mean(gray))

        failures = []

        if w < MIN_FACE_WIDTH or h < MIN_FACE_HEIGHT:
            failures.append("move_closer")

        if face_area_ratio < MIN_FACE_AREA_RATIO:
            failures.append("move_closer")

        if face_area_ratio > MAX_FACE_AREA_RATIO:
            failures.append("move_back")

        if offset_x > MAX_CENTER_OFFSET_X:
            failures.append("center_face")

        if offset_y > MAX_CENTER_OFFSET_Y:
            failures.append("center_face")

        if blur_score < MIN_BLUR_SCORE:
            failures.append("image_blurry")

        if brightness < MIN_BRIGHTNESS:
            failures.append("too_dark")

        if brightness > MAX_BRIGHTNESS:
            failures.append("too_bright")

        # Remove duplicates while preserving order.
        failures = list(dict.fromkeys(failures))

        return {
            "passed": len(failures) == 0,
            "failures": failures,
            "face_width": round(w, 2),
            "face_height": round(h, 2),
            "face_area_ratio": round(face_area_ratio, 4),
            "center_offset_x": round(offset_x, 4),
            "center_offset_y": round(offset_y, 4),
            "blur_score": round(blur_score, 2),
            "brightness": round(brightness, 2),
        }