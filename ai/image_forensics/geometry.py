from pathlib import Path

import cv2
import numpy as np


def analyze_geometry(image_path):
    """
    Analyze document image quality and geometry.

    This does NOT determine whether a document is genuine.
    It produces forensic/image-quality signals that are later
    combined with other evidence.
    """

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    image = cv2.imread(
        str(image_path)
    )

    if image is None:
        raise ValueError(
            f"Unable to read image: {image_path}"
        )

    height, width = image.shape[:2]

    # -----------------------------------------------------
    # 1. Resolution
    # -----------------------------------------------------

    megapixels = (
        width * height
    ) / 1_000_000

    # Preserve original resolution metadata, but perform expensive edge and
    # blur operations on a bounded working image.
    from backend.config import settings
    if max(height, width) > settings.analysis_max_dimension:
        scale = settings.analysis_max_dimension / max(height, width)
        image = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    working_height, working_width = image.shape[:2]

    # -----------------------------------------------------
    # 2. Aspect ratio
    # -----------------------------------------------------

    aspect_ratio = width / height

    # Passport/document images are commonly landscape.
    # This is only a weak signal because images may be
    # rotated or cropped.
    if aspect_ratio >= 1.2:
        orientation = "LANDSCAPE"

    elif aspect_ratio <= 0.83:
        orientation = "PORTRAIT"

    else:
        orientation = "SQUARE_OR_NEAR_SQUARE"

    # -----------------------------------------------------
    # 3. Blur detection using Laplacian variance
    # -----------------------------------------------------

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    if brightness < 45:
        exposure_status = "TOO_DARK"
    elif brightness > 225:
        exposure_status = "TOO_BRIGHT"
    else:
        exposure_status = "BALANCED"

    if contrast < 22:
        contrast_status = "LOW"
    elif contrast < 38:
        contrast_status = "ACCEPTABLE"
    else:
        contrast_status = "GOOD"

    laplacian = cv2.Laplacian(
        gray,
        cv2.CV_64F
    )

    blur_score = float(
        laplacian.var()
    )

    if blur_score < 50:
        blur_status = "VERY_BLURRY"

    elif blur_score < 100:
        blur_status = "BLURRY"

    elif blur_score < 250:
        blur_status = "ACCEPTABLE"

    else:
        blur_status = "SHARP"

    # -----------------------------------------------------
    # 4. Rotation estimation
    # -----------------------------------------------------

    edges = cv2.Canny(
        gray,
        50,
        150
    )

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=80,
        minLineLength=max(
            50,
            working_width // 5
        ),
        maxLineGap=20
    )

    angles = []

    if lines is not None:

        for line in lines:

            x1, y1, x2, y2 = line.ravel()

            angle = np.degrees(
                np.arctan2(
                    y2 - y1,
                    x2 - x1
                )
            )

            # Normalize angle to [-90, 90]
            if angle < -90:
                angle += 180

            if angle > 90:
                angle -= 180

            # We only care about nearly horizontal/
            # vertical document edges.
            if abs(angle) <= 20:
                angles.append(angle)

    if angles:

        median_angle = float(
            np.median(
                np.abs(angles)
            )
        )

    else:
        median_angle = 0.0

    if median_angle > 10:
        rotation_status = "HIGH_ROTATION"

    elif median_angle > 3:
        rotation_status = "SLIGHT_ROTATION"

    else:
        rotation_status = "ALIGNED"

    # -----------------------------------------------------
    # 5. Resolution quality
    # -----------------------------------------------------

    if megapixels < 0.5:
        resolution_status = "VERY_LOW"

    elif megapixels < 1.0:
        resolution_status = "LOW"

    elif megapixels < 2.0:
        resolution_status = "ACCEPTABLE"

    else:
        resolution_status = "HIGH"

    # -----------------------------------------------------
    # 6. Build quality signals
    # -----------------------------------------------------

    signals = []

    if resolution_status in {
        "VERY_LOW",
        "LOW"
    }:
        signals.append(
            "LOW_IMAGE_RESOLUTION"
        )

    if blur_status in {
        "VERY_BLURRY",
        "BLURRY"
    }:
        signals.append(
            "IMAGE_BLUR"
        )

    if rotation_status == "HIGH_ROTATION":
        signals.append(
            "HIGH_DOCUMENT_ROTATION"
        )

    if exposure_status != "BALANCED":
        signals.append("POOR_IMAGE_EXPOSURE")

    if contrast_status == "LOW":
        signals.append("LOW_IMAGE_CONTRAST")

    # -----------------------------------------------------
    # 7. Calculate geometry score
    # -----------------------------------------------------

    score = 0.0

    if resolution_status == "VERY_LOW":
        score += 30

    elif resolution_status == "LOW":
        score += 15

    if blur_status == "VERY_BLURRY":
        score += 30

    elif blur_status == "BLURRY":
        score += 15

    if rotation_status == "HIGH_ROTATION":
        score += 20

    elif rotation_status == "SLIGHT_ROTATION":
        score += 5

    if exposure_status != "BALANCED":
        score += 20

    if contrast_status == "LOW":
        score += 20

    score = min(
        100.0,
        score
    )

    if score >= 50:
        risk_level = "HIGH"

    elif score >= 25:
        risk_level = "MEDIUM"

    else:
        risk_level = "LOW"

    return {
        "image_dimensions": {
            "width": width,
            "height": height,
            "megapixels": round(
                megapixels,
                3
            )
        },

        "aspect_ratio": round(
            aspect_ratio,
            3
        ),

        "orientation": orientation,

        "blur": {
            "score": round(
                blur_score,
                2
            ),
            "status": blur_status
        },

        "illumination": {
            "mean_brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
            "exposure_status": exposure_status,
            "contrast_status": contrast_status,
        },

        "rotation": {
            "estimated_degrees": round(
                median_angle,
                2
            ),
            "status": rotation_status
        },

        "resolution": {
            "status": resolution_status
        },

        "overall": {
            "score": round(
                score,
                2
            ),
            "risk_level": risk_level,
            "signals": signals
        },

        "capture_quality": {
            "score": round(max(0.0, 100.0 - score), 2),
            "status": "RECAPTURE" if score >= 50 else "REVIEW" if score >= 25 else "PASS",
            "blocking": score >= 50,
            "signals": signals,
            "guidance": [
                message
                for condition, message in (
                    ("LOW_IMAGE_RESOLUTION" in signals, "Move closer or use a higher-resolution camera."),
                    ("IMAGE_BLUR" in signals, "Hold the document and camera steady, then recapture."),
                    ("HIGH_DOCUMENT_ROTATION" in signals, "Align all document edges with the capture frame."),
                    (exposure_status == "TOO_DARK", "Increase even ambient lighting without using flash."),
                    (exposure_status == "TOO_BRIGHT", "Reduce direct light and avoid reflective glare."),
                    (contrast_status == "LOW", "Use a contrasting background and refocus the camera."),
                )
                if condition
            ],
        },
    }


if __name__ == "__main__":

    import json
    import sys

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python geometry.py "
            "<image_path>"
        )

        sys.exit(1)

    image_path = sys.argv[1]

    result = analyze_geometry(
        image_path
    )

    print("=" * 60)
    print("DOCUMENT GEOMETRY ANALYSIS")
    print("=" * 60)
    print()

    print(
        json.dumps(
            result,
            indent=4
        )
    )

    print()
    print("=" * 60)
    print("GEOMETRY ANALYSIS COMPLETE")
    print("=" * 60)
