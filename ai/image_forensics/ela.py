from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageEnhance


def _analysis_size(image):
    from backend.config import settings
    maximum = settings.analysis_max_dimension
    width, height = image.size
    scale = min(1.0, maximum / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def perform_ela(
    image_path,
    quality=90,
    scale=10,
    grid_size=4,
):
    """
    Perform Error Level Analysis (ELA).

    Returns:
        {
            "ela_score": float,
            "mean_error": float,
            "max_error": float,
            "suspicious": bool
        }
    """

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    original = Image.open(
        image_path
    ).convert("RGB")
    analysis_size = _analysis_size(original)
    if original.size != analysis_size:
        original.thumbnail(analysis_size, Image.Resampling.LANCZOS)

    # Temporary in-memory recompression
    import io

    buffer = io.BytesIO()

    original.save(
        buffer,
        format="JPEG",
        quality=quality
    )

    buffer.seek(0)

    recompressed = Image.open(
        buffer
    ).convert("RGB")

    # Calculate pixel difference
    difference = ImageChops.difference(
        original,
        recompressed
    )

    # Enhance differences
    enhanced = ImageEnhance.Brightness(
        difference
    ).enhance(scale)

    # Convert to NumPy
    ela_array = np.asarray(
        enhanced
    ).astype(np.float32)

    # Per-pixel average error
    error_map = np.mean(
        ela_array,
        axis=2
    )

    mean_error = float(
        np.mean(error_map)
    )

    max_error = float(
        np.max(error_map)
    )

    height, width = error_map.shape
    regional_means = []

    for row in range(grid_size):
        for column in range(grid_size):
            y1 = row * height // grid_size
            y2 = (row + 1) * height // grid_size
            x1 = column * width // grid_size
            x2 = (column + 1) * width // grid_size
            region = error_map[y1:y2, x1:x2]
            if region.size:
                regional_means.append((float(np.mean(region)), x1, y1, x2, y2))

    regional_values = np.array([region[0] for region in regional_means])
    region_threshold = mean_error + max(
        5.0,
        float(np.std(regional_values)) * 2.0 if regional_values.size else 0.0,
    )
    suspicious_regions = [
        {
            "bbox": [x1, y1, x2, y2],
            "mean_error": round(region_mean, 2),
        }
        for region_mean, x1, y1, x2, y2 in regional_means
        if region_mean >= region_threshold
    ]
    suspicious_regions.sort(key=lambda region: region["mean_error"], reverse=True)

    # Normalize to 0–100
    ela_score = min(
        100.0,
        (mean_error / 255.0) * 100.0
    )

    # This threshold is deliberately conservative.
    suspicious = ela_score >= 15.0 or bool(suspicious_regions)

    return {
        "ela_score": round(
            ela_score,
            2
        ),
        "mean_error": round(
            mean_error,
            2
        ),
        "max_error": round(
            max_error,
            2
        ),
        "suspicious": suspicious,
        "suspicious_regions": suspicious_regions[:5],
        "region_threshold": round(region_threshold, 2),
    }
