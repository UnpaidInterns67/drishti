"""File and image-metadata signals for document screening."""

import hashlib
from pathlib import Path

from PIL import ExifTags, Image


EDITOR_MARKERS = (
    "adobe",
    "photoshop",
    "gimp",
    "lightroom",
    "picsart",
    "snapseed",
    "canva",
)


def _serializable(value):
    if isinstance(value, bytes):
        return value.hex()[:256]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def analyze_metadata(image_path):
    """Inspect image format, hash, and non-sensitive EXIF editing signals."""
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()

    with Image.open(image_path) as image:
        detected_format = image.format
        width, height = image.size
        exif = {
            ExifTags.TAGS.get(tag, str(tag)): _serializable(value)
            for tag, value in image.getexif().items()
        }

    software = str(exif.get("Software", ""))
    software_lower = software.lower()
    editor_detected = next(
        (marker for marker in EDITOR_MARKERS if marker in software_lower),
        None,
    )

    expected_formats = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
        ".tif": "TIFF",
        ".tiff": "TIFF",
    }
    expected_format = expected_formats.get(image_path.suffix.lower())
    extension_mismatch = bool(
        expected_format
        and detected_format
        and expected_format != detected_format
    )

    signals = []
    if editor_detected:
        signals.append("EDITING_SOFTWARE_METADATA")
    if extension_mismatch:
        signals.append("FILE_EXTENSION_FORMAT_MISMATCH")

    score = min(
        100.0,
        (40.0 if editor_detected else 0.0)
        + (30.0 if extension_mismatch else 0.0),
    )

    return {
        "sha256": digest,
        "format": detected_format,
        "dimensions": {"width": width, "height": height},
        "exif_present": bool(exif),
        "software": software or None,
        "editor_marker": editor_detected,
        "extension_mismatch": extension_mismatch,
        "metadata_score": score,
        "suspicious": bool(signals),
        "signals": signals,
    }
