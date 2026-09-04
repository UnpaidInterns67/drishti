from pathlib import Path

import cv2
import numpy as np


def analyze_noise(image_path):
    """
    Analyze local noise consistency in a document image.

    Returns a score indicating how different local regions are
    from the overall noise distribution.

    This is a forensic signal, NOT proof of manipulation.
    """

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    image = cv2.imread(
        str(image_path),
        cv2.IMREAD_GRAYSCALE
    )

    if image is None:
        raise ValueError(
            f"Unable to read image: {image_path}"
        )

    # Estimate sensor/compression residual only in locally flat pixels. The old
    # implementation averaged all high-frequency content, so portraits, text,
    # logos, and blank card areas inevitably appeared to have different "noise".
    image_float = image.astype(np.float32)
    blurred = cv2.GaussianBlur(image_float, (5, 5), 0)
    residual = np.abs(image_float - blurred)
    gradient_x = cv2.Sobel(image_float, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(image_float, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)

    # Divide image into regions.
    height, width = residual.shape

    grid_rows = 4
    grid_cols = 4

    region_scores = []

    for row in range(grid_rows):
        for col in range(grid_cols):

            y1 = row * height // grid_rows
            y2 = (row + 1) * height // grid_rows

            x1 = col * width // grid_cols
            x2 = (col + 1) * width // grid_cols

            region_residual = residual[
                y1:y2,
                x1:x2
            ]
            region_gradient = gradient[y1:y2, x1:x2]

            if region_residual.size == 0:
                continue

            flat_threshold = float(np.percentile(region_gradient, 60))
            flat_residual = region_residual[region_gradient <= flat_threshold]
            if flat_residual.size < 100:
                continue
            score = float(np.median(flat_residual))

            region_scores.append({
                "row": row,
                "column": col,
                "noise_median": round(
                    score,
                    2
                ),
                "noise_mean": round(score, 2),
            })

    if not region_scores:
        return {
            "noise_score": 0.0,
            "suspicious": False,
            "regions": []
        }

    values = np.array([
        region["noise_mean"]
        for region in region_scores
    ])

    median_noise = float(np.median(values))
    mad_noise = float(np.median(np.abs(values - median_noise)))
    variation = mad_noise / max(median_noise, 1.0)

    absolute_spread = float(np.max(values) - np.min(values))
    # MAD captures broad inconsistency; absolute spread also catches a localized
    # pasted/noisy block when most genuine flat regions have near-zero residual.
    noise_score = min(
        100.0,
        max(variation * 100.0, absolute_spread * 5.0),
    )
    suspicious = noise_score >= 55.0 and absolute_spread >= 1.5

    return {
        "noise_score": round(
            noise_score,
            2
        ),
        "mean_noise": round(
            median_noise,
            2
        ),
        "noise_std": round(
            mad_noise,
            2
        ),
        "method": "FLAT_REGION_MEDIAN_RESIDUAL",
        "absolute_spread": round(absolute_spread, 2),
        "suspicious": suspicious,
        "regions": region_scores
    }


if __name__ == "__main__":

    import json
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python noise_analysis.py "
            "<image_path>"
        )
        sys.exit(1)

    image_path = sys.argv[1]

    result = analyze_noise(
        image_path
    )

    print(
        json.dumps(
            result,
            indent=4
        )
    )
