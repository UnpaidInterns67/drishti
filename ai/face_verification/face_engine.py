from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .config import (
    FACE_DETECTION_THRESHOLD,
    FACE_NMS_THRESHOLD,
    FACE_TOP_K,
    SFACE_MODEL,
    YUNET_MODEL,
)


class FaceEngine:
    def __init__(
        self,
        detector_model: str | Path = YUNET_MODEL,
        recognition_model: str | Path = SFACE_MODEL,
    ):
        self.detector_model = str(detector_model)
        self.recognition_model = str(recognition_model)

        self._validate_models()

        self.detector = cv2.FaceDetectorYN.create(
            self.detector_model,
            "",
            (320, 320),
            FACE_DETECTION_THRESHOLD,
            FACE_NMS_THRESHOLD,
            FACE_TOP_K,
        )

        self.recognizer = cv2.FaceRecognizerSF.create(
            self.recognition_model,
            "",
        )

    def _validate_models(self):
        if not Path(self.detector_model).exists():
            raise FileNotFoundError(
                f"YuNet model not found: {self.detector_model}"
            )

        if not Path(self.recognition_model).exists():
            raise FileNotFoundError(
                f"SFace model not found: {self.recognition_model}"
            )

    def detect_faces(self, image: np.ndarray) -> np.ndarray:
        if image is None or image.size == 0:
            return np.empty((0, 15), dtype=np.float32)

        height, width = image.shape[:2]

        self.detector.setInputSize((width, height))

        _, faces = self.detector.detect(image)

        if faces is None:
            return np.empty((0, 15), dtype=np.float32)

        return faces

    @staticmethod
    def largest_face(faces: np.ndarray):
        if faces is None or len(faces) == 0:
            return None

        areas = faces[:, 2] * faces[:, 3]
        index = int(np.argmax(areas))

        return faces[index]

    def detect_largest_face(self, image: np.ndarray):
        faces = self.detect_faces(image)
        return self.largest_face(faces)

    def aligned_face(self, image: np.ndarray, face) -> np.ndarray:
        if face is None:
            raise ValueError("Cannot align face: face is None.")

        return self.recognizer.alignCrop(image, face)

    def embedding(self, image: np.ndarray, face) -> np.ndarray:
        aligned = self.aligned_face(image, face)

        feature = self.recognizer.feature(aligned)

        return feature.copy()

    def cosine_similarity(
        self,
        embedding_a: np.ndarray,
        embedding_b: np.ndarray,
    ) -> float:
        score = self.recognizer.match(
            embedding_a,
            embedding_b,
            cv2.FaceRecognizerSF_FR_COSINE,
        )

        return float(score)

    @staticmethod
    def box(face):
        x, y, w, h = face[:4]

        return (
            int(x),
            int(y),
            int(w),
            int(h),
        )

    @staticmethod
    def confidence(face) -> float:
        return float(face[-1])

    @staticmethod
    def draw_face(image, face, color=(0, 255, 0)):
        x, y, w, h = FaceEngine.box(face)

        cv2.rectangle(
            image,
            (x, y),
            (x + w, y + h),
            color,
            2,
        )

        return image