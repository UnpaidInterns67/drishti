from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from .config import (
    FACE_MATCH_UNCERTAINTY_MARGIN,
    HEAD_CENTER_THRESHOLD,
    MAX_STABLE_EMBEDDING_SAMPLES,
    MIN_STABLE_EMBEDDING_SAMPLES,
    RECOMMENDED_MATCH_THRESHOLD,
)
from .face_engine import FaceEngine
from .liveness import LivenessDetector
from .quality import FaceQualityChecker
from .utils import put_text


def stable_similarity(id_embedding, live_embeddings, similarity_function):
    """Return robust face similarity statistics across independent frames."""
    scores = [
        float(similarity_function(id_embedding, embedding))
        for embedding in live_embeddings
        if embedding is not None
    ]
    if not scores:
        return None
    # The median limits the influence of a single unusually good or bad frame.
    return {
        "median": round(float(np.median(scores)), 4),
        "minimum": round(float(np.min(scores)), 4),
        "maximum": round(float(np.max(scores)), 4),
        "spread": round(float(np.max(scores) - np.min(scores)), 4),
        "samples": len(scores),
    }


class IdentityVerifier:
    def __init__(self, match_threshold: float = RECOMMENDED_MATCH_THRESHOLD):
        self.face_engine = FaceEngine()
        self.quality_checker = FaceQualityChecker()
        self.match_threshold = match_threshold

        self.session_active = False
        self.id_embedding = None
        self.liveness = None

        self.best_live_embedding = None
        self.best_face_confidence = 0.0
        self.live_embedding_samples = []

        self.no_face_frames = 0
        self.multi_face_frames = 0
        self.final_result = None

    def load_id_embedding(self, id_image_path: str | Path):
        id_image_path = Path(id_image_path)

        image = cv2.imread(str(id_image_path))

        if image is None:
            raise ValueError(
                f"Could not open ID image: {id_image_path}"
            )

        faces = self.face_engine.detect_faces(image)

        if len(faces) == 0:
            raise ValueError(
                "No face detected in uploaded ID image."
            )

        face = self.face_engine.largest_face(faces)

        embedding = self.face_engine.embedding(
            image,
            face,
        )

        return {
            "embedding": embedding,
            "face": face,
            "image": image,
            "faces_detected": len(faces),
        }

    def start_session(self, id_image) -> dict:
        """
        Start a new face verification session.

        id_image:
            Either:
            - path string
            - pathlib.Path
            - OpenCV BGR numpy image
        """

        self.no_face_frames = 0
        self.multi_face_frames = 0

        if isinstance(id_image, (str, Path)):
            image = cv2.imread(str(id_image))

            if image is None:
                raise ValueError(
                    f"Could not load ID image: {id_image}"
                )
        else:
            image = id_image

        faces = self.face_engine.detect_faces(image)

        if len(faces) == 0:
            return {
                "started": False,
                "reason": "no_face_in_id",
            }

        face = self.face_engine.largest_face(faces)

        self.id_embedding = self.face_engine.embedding(
            image,
            face,
        )

        if self.liveness is not None:
            self.liveness.close()

        self.liveness = LivenessDetector()

        self.best_live_embedding = None
        self.best_face_confidence = 0.0
        self.live_embedding_samples = []

        self.final_result = None
        self.session_active = True

        return {
            "started": True,
            "id_faces_detected": int(len(faces)),
            "state": "BLINK",
            "instruction": "Look at the camera and keep your eyes open",
        }

    def process_frame(self, frame, *, mirror_liveness=False) -> dict:
        """
        Process ONE camera frame.

        Input:
            OpenCV BGR numpy image.

        Output:
            Python dict safe for JSON serialization.
        """

        if not self.session_active:
            return {
                "error": "no_active_session",
            }

        if self.final_result is not None:
            return self.final_result

        if frame is None or frame.size == 0:
            self.live_embedding_samples.clear()
            return {
                "state": "WAITING",
                "reason": "invalid_frame",
            }

        faces = self.face_engine.detect_faces(frame)

        if len(faces) == 0:
            self.no_face_frames += 1
            self.live_embedding_samples.clear()

            # Ignore a couple of temporary detection misses.
            if self.no_face_frames < 3:
                return {
                    "state": self.liveness.state,
                    "face_detected": False,
                    "temporary": True,
                    "instruction": self.liveness.instruction(),
                }

            return {
                "state": "WAITING",
                "face_detected": False,
                "instruction": "Position your face in the frame",
            }

        self.no_face_frames = 0

        if len(faces) > 1:
            self.multi_face_frames += 1
            self.live_embedding_samples.clear()

            if self.multi_face_frames < 3:
                return {
                    "state": self.liveness.state,
                    "face_detected": True,
                    "temporary": True,
                    "instruction": self.liveness.instruction(),
                }

            return {
                "state": "WAITING",
                "face_detected": True,
                "multiple_faces": True,
                "instruction": "Only one person should be visible",
            }

        self.multi_face_frames = 0

        face = self.face_engine.largest_face(faces)

        quality = self.quality_checker.evaluate(
            frame,
            face,
        )

        if not quality["passed"]:
            self.live_embedding_samples.clear()
            failures = quality.get(
                "failures",
                [],
            )

            return {
                "state": "QUALITY",
                "face_detected": True,
                "quality_passed": False,
                "quality": quality,
                "capture_stability": self._capture_stability(),
                "instruction": (
                    self._quality_instruction(failures)
                    if failures
                    else "Adjust your position"
                ),
            }

        rgb = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB,
        )
        # Mirror only the challenge view so left/right instructions retain
        # their browser meaning. Recognition uses the original camera image.
        if mirror_liveness:
            rgb = cv2.flip(rgb, 1)

        live_result = self.liveness.process(rgb)

        confidence = self.face_engine.confidence(
            face
        )

        # Challenge motion and closed-eye frames are not recognition samples.
        # Collect a fresh consecutive set only after the user faces forward.
        yaw = live_result.get("relative_yaw", live_result.get("yaw_signal"))
        ear = live_result.get("ear")
        open_baseline = getattr(self.liveness, "open_ear_baseline", None)
        capture_ready = (
            live_result.get("passed", False)
            and yaw is not None and np.isfinite(yaw)
            and abs(yaw) <= HEAD_CENTER_THRESHOLD
            and ear is not None and np.isfinite(ear)
            and ear >= (open_baseline * 0.86 if open_baseline else 0.23)
        )
        if capture_ready:
            try:
                self._record_embedding(
                    self.face_engine.embedding(frame, face), confidence,
                )
            except cv2.error:
                self.live_embedding_samples.clear()
        else:
            self.live_embedding_samples.clear()

        if live_result.get("failed"):
            self.final_result = {
                "verification_passed": False,
                "face_match": False,
                "liveness_passed": False,
                "liveness_score": live_result.get(
                    "score",
                    0.0,
                ),
                "reason": live_result.get(
                    "reason",
                    "liveness_failed",
                ),
            }

            self.session_active = False

            return self.final_result

        if not live_result.get("passed"):
            return {
                "state": live_result.get(
                    "state",
                    "UNKNOWN",
                ),
                "face_detected": True,
                "quality_passed": True,
                "liveness_passed": False,
                "liveness_score": live_result.get(
                    "score",
                    0.0,
                ),
                "blink_detected": live_result.get(
                    "blink_detected",
                    False,
                ),
                "blink_ready": live_result.get(
                    "blink_ready",
                    False,
                ),
                "blink_progress": live_result.get(
                    "blink_progress",
                    0,
                ),
                "eye_aspect_ratio": live_result.get("ear"),
                "head_turn_detected": live_result.get(
                    "head_turn_detected",
                    False,
                ),
                "instruction": live_result.get(
                    "instruction",
                    "Follow the liveness challenge",
                ),
                "quality": quality,
                "capture_stability": self._capture_stability(),
            }

        if len(self.live_embedding_samples) < MIN_STABLE_EMBEDDING_SAMPLES:
            return {
                "state": "STABILIZING",
                "face_detected": True,
                "quality_passed": True,
                "liveness_passed": True,
                "instruction": "Look straight at the camera, eyes open, and hold still for the face comparison",
                "quality": quality,
                "capture_stability": self._capture_stability(),
            }

        similarity_stats = stable_similarity(
            self.id_embedding,
            [sample["embedding"] for sample in self.live_embedding_samples],
            self.face_engine.cosine_similarity,
        )
        if similarity_stats is None:
            self.final_result = {
                "verification_passed": False,
                "liveness_passed": True,
                "face_match": False,
                "reason": "live_embedding_failed",
            }

            self.session_active = False

            return self.final_result

        similarity = similarity_stats["median"]

        is_match = (
            similarity >= self.match_threshold
        )

        self.final_result = {
            "verification_passed": bool(is_match),
            "face_match": bool(is_match),
            "face_similarity": round(
                similarity,
                4,
            ),
            "face_match_threshold": (
                self.match_threshold
            ),
            "face_match_margin": FACE_MATCH_UNCERTAINTY_MARGIN,
            "face_similarity_min": similarity_stats["minimum"],
            "face_similarity_max": similarity_stats["maximum"],
            "face_similarity_spread": similarity_stats["spread"],
            "face_samples": similarity_stats["samples"],
            "liveness_passed": True,
            "liveness_score": live_result.get(
                "score",
                1.0,
            ),
            "blink_detected": live_result.get(
                "blink_detected",
                False,
            ),
            "head_turn_detected": live_result.get(
                "head_turn_detected",
                False,
            ),
            "head_turn_direction": live_result.get(
                "turn_direction",
            ),
            "face_detection_confidence": round(
                confidence,
                4,
            ),
            "quality": quality,
            "capture_stability": self._capture_stability(),
        }

        self.session_active = False

        return self.final_result

    def _record_embedding(self, embedding, confidence):
        if embedding is None:
            return
        self.live_embedding_samples.append({
            "embedding": embedding,
            "confidence": float(confidence),
        })
        self.live_embedding_samples.sort(
            key=lambda sample: sample["confidence"],
            reverse=True,
        )
        del self.live_embedding_samples[MAX_STABLE_EMBEDDING_SAMPLES:]
        self.best_live_embedding = self.live_embedding_samples[0]["embedding"]
        self.best_face_confidence = self.live_embedding_samples[0]["confidence"]

    def _capture_stability(self):
        count = len(self.live_embedding_samples)
        return {
            "samples": count,
            "required_samples": MIN_STABLE_EMBEDDING_SAMPLES,
            "progress": round(min(1.0, count / MIN_STABLE_EMBEDDING_SAMPLES), 3),
            "stable": count >= MIN_STABLE_EMBEDDING_SAMPLES,
        }

    @staticmethod
    def _quality_instruction(failures):
        guidance = {
            "move_closer": "Move closer to the camera",
            "move_back": "Move slightly away from the camera",
            "center_face": "Center your full face inside the oval",
            "image_blurry": "Hold still and keep the camera steady",
            "too_dark": "Move into even front lighting",
            "too_bright": "Move away from glare or strong backlight",
        }
        return guidance.get(failures[0], "Adjust your position")

    def get_result(self):
        return self.final_result

    def close_session(self):
        if self.liveness is not None:
            self.liveness.close()
            self.liveness = None

        self.session_active = False

    def run_webcam_verification(
        self,
        id_image_path: str | Path,
        camera_index: int = 0,
    ) -> dict:

        id_data = self.load_id_embedding(
            id_image_path
        )

        id_embedding = id_data["embedding"]

        camera = cv2.VideoCapture(
            camera_index,
            cv2.CAP_DSHOW,
        )

        if not camera.isOpened():
            # Retry using default OpenCV backend.
            camera.release()

            camera = cv2.VideoCapture(camera_index)

        if not camera.isOpened():
            raise RuntimeError(
                "Could not open webcam."
            )

        camera.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            1280,
        )

        camera.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            720,
        )

        liveness = LivenessDetector()

        best_live_embedding = None
        best_quality = None
        best_face_confidence = 0.0
        best_frame = None

        final_result = None

        try:
            while True:
                success, frame = camera.read()

                if not success:
                    print("[DEBUG] Camera frame read failed")
                    continue

                frame = cv2.flip(frame, 1)
                display = frame.copy()

                faces = self.face_engine.detect_faces(frame)

                print(f"[DEBUG] Faces detected: {len(faces)}")

                if len(faces) == 0:
                    cv2.imshow("Identity Verification", display)

                    if self._quit_pressed():
                        final_result = {
                            "verification_passed": False,
                            "cancelled": True,
                            "reason": "user_cancelled",
                        }
                        break

                    continue

                if len(faces) > 1:
                    cv2.imshow("Identity Verification", display)

                    if self._quit_pressed():
                        final_result = {
                            "verification_passed": False,
                            "cancelled": True,
                            "reason": "user_cancelled",
                        }
                        break

                    continue

                face = self.face_engine.largest_face(faces)

                self.face_engine.draw_face(display, face)

                quality = self.quality_checker.evaluate(
                    frame,
                    face,
                )

                print(
                    "[DEBUG] Quality:",
                    quality["passed"],
                    quality.get("failures", []),
                    "blur=",
                    quality.get("blur_score"),
                    "area=",
                    quality.get("face_area_ratio"),
                )

                if not quality["passed"]:
                    cv2.imshow("Identity Verification", display)

                    if self._quit_pressed():
                        final_result = {
                            "verification_passed": False,
                            "cancelled": True,
                            "reason": "user_cancelled",
                        }
                        break

                    continue

                rgb = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2RGB,
                )

                live_result = liveness.process(rgb)

                print(
                    "[DEBUG] Liveness:",
                    live_result.get("state"),
                    live_result.get("score"),
                    live_result.get("instruction"),
                )

                confidence = self.face_engine.confidence(face)

                if confidence > best_face_confidence:
                    try:
                        best_live_embedding = (
                            self.face_engine.embedding(
                                frame,
                                face,
                            )
                        )

                        best_quality = quality
                        best_face_confidence = confidence
                        best_frame = frame.copy()

                    except cv2.error:
                        pass

                if live_result.get("failed"):
                    final_result = {
                        "verification_passed": False,
                        "face_match": False,
                        "liveness_passed": False,
                        "liveness_score": live_result.get(
                            "score",
                            0.0,
                        ),
                        "reason": live_result.get(
                            "reason",
                            "liveness_failed",
                        ),
                    }

                    self._show_final(
                        display,
                        final_result,
                    )

                    break

                if live_result.get("passed"):
                    print(
                        "[DEBUG] Liveness passed. Comparing faces..."
                    )

                    try:
                        live_embedding = (
                            self.face_engine.embedding(
                                frame,
                                face,
                            )
                        )

                    except cv2.error:
                        live_embedding = best_live_embedding

                    if live_embedding is None:
                        final_result = {
                            "verification_passed": False,
                            "face_match": False,
                            "liveness_passed": True,
                            "liveness_score": live_result.get(
                                "score",
                                1.0,
                            ),
                            "reason": "live_embedding_failed",
                        }

                        self._show_final(
                            display,
                            final_result,
                        )

                        break

                    similarity = (
                        self.face_engine.cosine_similarity(
                            id_embedding,
                            live_embedding,
                        )
                    )

                    print(
                        f"[DEBUG] Face similarity: "
                        f"{similarity:.4f}"
                    )

                    is_match = (
                        similarity >= self.match_threshold
                    )

                    print(
                        f"[DEBUG] Face match: {is_match}"
                    )

                    final_result = {
                        "verification_passed": bool(is_match),
                        "face_match": bool(is_match),
                        "face_similarity": round(
                            similarity,
                            4,
                        ),
                        "face_match_threshold": (
                            self.match_threshold
                        ),
                        "liveness_passed": True,
                        "liveness_score": live_result.get(
                            "score",
                            1.0,
                        ),
                        "blink_detected": live_result.get(
                            "blink_detected",
                            False,
                        ),
                        "head_turn_detected": live_result.get(
                            "head_turn_detected",
                            False,
                        ),
                        "head_turn_direction": (
                            live_result.get(
                                "turn_direction"
                            )
                        ),
                        "face_detection_confidence": round(
                            confidence,
                            4,
                        ),
                        "quality": quality,
                        "id_faces_detected": (
                            id_data["faces_detected"]
                        ),
                    }

                    self._show_final(
                        display,
                        final_result,
                    )

                    break

                cv2.imshow(
                    "Identity Verification",
                    display,
                )

                if self._quit_pressed():
                    final_result = {
                        "verification_passed": False,
                        "cancelled": True,
                        "reason": "user_cancelled",
                    }

                    break

        finally:
            camera.release()
            cv2.destroyAllWindows()
            liveness.close()

        if final_result is None:
            return {
                "verification_passed": False,
                "reason": "verification_ended",
            }

        return final_result

    @staticmethod
    def _draw_footer(
        image,
        liveness,
    ):
        put_text(
            image,
            "Press Q to cancel",
            (30, image.shape[0] - 30),
            (180, 180, 180),
            0.5,
            1,
        )

    @staticmethod
    def _quit_pressed():
        key = cv2.waitKey(1) & 0xFF
        return key == ord("q")

    @staticmethod
    def _show_final(
        display,
        result,
    ):
        passed = result.get(
            "verification_passed",
            False,
        )

        if passed:
            message = "VERIFICATION PASSED"
            color = (0, 255, 0)

        else:
            message = "VERIFICATION FAILED"
            color = (0, 0, 255)

        put_text(
            display,
            message,
            (30, 190),
            color,
            1.0,
            3,
        )

        similarity = result.get(
            "face_similarity"
        )

        if similarity is not None:
            put_text(
                display,
                f"Face similarity: {similarity:.3f}",
                (30, 230),
                color,
            )

        cv2.imshow(
            "Identity Verification",
            display,
        )

        # Leave final result visible briefly.
        cv2.waitKey(1800)
