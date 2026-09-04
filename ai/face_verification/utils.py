from __future__ import annotations

import cv2
import numpy as np


def euclidean_distance(p1, p2) -> float:
    p1 = np.asarray(p1, dtype=np.float32)
    p2 = np.asarray(p2, dtype=np.float32)
    return float(np.linalg.norm(p1 - p2))


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def put_text(
    image,
    text: str,
    position: tuple[int, int],
    color=(255, 255, 255),
    scale: float = 0.65,
    thickness: int = 2,
):
    cv2.putText(
        image,
        text,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def normalized_landmark(landmark, frame_width: int, frame_height: int):
    return np.array(
        [
            landmark.x * frame_width,
            landmark.y * frame_height,
        ],
        dtype=np.float32,
    )