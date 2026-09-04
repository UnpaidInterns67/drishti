import json
import sys
from pathlib import Path

if __package__:
    from .ela import perform_ela
    from .geometry import analyze_geometry
    from .metadata import analyze_metadata
    from .noise_analysis import analyze_noise
else:
    from ela import perform_ela
    from geometry import analyze_geometry
    from metadata import analyze_metadata
    from noise_analysis import analyze_noise


def analyze_image_forensics(image_path):
    """
    Run all image-forensic checks and combine them.

    Current detectors:
        1. ELA
        2. Noise consistency
        3. Image/document geometry

    IMPORTANT:
    These are forensic risk signals.
    They do NOT prove that a document is fake.
    """

    image_path = Path(image_path)

    if not image_path.exists():
        raise FileNotFoundError(
            f"Image not found: {image_path}"
        )

    # =====================================================
    # 1. ELA
    # =====================================================

    ela_result = perform_ela(
        image_path
    )

    # =====================================================
    # 2. NOISE
    # =====================================================

    noise_result = analyze_noise(
        image_path
    )

    # =====================================================
    # 3. GEOMETRY
    # =====================================================

    geometry_result = analyze_geometry(
        image_path
    )

    metadata_result = analyze_metadata(
        image_path
    )

    # =====================================================
    # 4. Extract scores
    # =====================================================

    ela_score = float(
        ela_result.get(
            "ela_score",
            0
        )
    )

    noise_score = float(
        noise_result.get(
            "noise_score",
            0
        )
    )

    geometry_score = float(
        geometry_result
        .get("overall", {})
        .get("score", 0)
    )
    capture_quality = geometry_result.get("capture_quality", {})

    metadata_score = float(
        metadata_result.get(
            "metadata_score",
            0
        )
    )

    # =====================================================
    # 5. Combined forensic score
    # =====================================================
    #
    # Current experimental weights:
    #
    # ELA       = 45%
    # Noise     = 35%
    # Metadata  = 20%
    #
    # These weights will later be calibrated against
    # genuine and manipulated document samples.
    #

    overall_score = (
        (ela_score * 0.45)
        +
        (noise_score * 0.35)
        +
        (metadata_score * 0.20)
    )

    overall_score = min(
        100.0,
        overall_score
    )

    # Do not let an explicit detector warning disappear in a weighted average.
    # These floors express evidence strength, not "forgery proven".
    detector_floors = []
    ela_suspicious = bool(ela_result.get("suspicious", False))
    noise_suspicious = bool(noise_result.get("suspicious", False))
    if ela_suspicious and noise_suspicious:
        detector_floors.append(45.0)
    elif ela_suspicious:
        detector_floors.append(25.0)
    elif noise_suspicious:
        detector_floors.append(25.0)
    metadata_signals = set(metadata_result.get("signals", []))
    if "EDITING_SOFTWARE_METADATA" in metadata_signals:
        detector_floors.append(45.0)
    if "FILE_EXTENSION_FORMAT_MISMATCH" in metadata_signals:
        detector_floors.append(35.0)
    if detector_floors:
        overall_score = max(overall_score, max(detector_floors))

    # =====================================================
    # 6. Risk level
    # =====================================================

    if overall_score >= 60:

        risk_level = "HIGH"

    elif overall_score >= 35:

        risk_level = "MEDIUM"

    else:

        risk_level = "LOW"

    # =====================================================
    # 7. Collect forensic signals
    # =====================================================

    signals = []

    if ela_result.get(
        "suspicious",
        False
    ):

        signals.append({
            "type": "IMAGE_FORENSICS",
            "signal": "ELA_ANOMALY",
            "score": ela_score,
            "severity": "MEDIUM",
            "regions": ela_result.get("suspicious_regions", [])
        })

    if noise_result.get(
        "suspicious",
        False
    ):

        signals.append({
            "type": "IMAGE_FORENSICS",
            "signal": "NOISE_INCONSISTENCY",
            "score": noise_score,
            "severity": "MEDIUM"
        })

    geometry_signals = (
        geometry_result
        .get("overall", {})
        .get("signals", [])
    )

    for signal in geometry_signals:

        signals.append({
            "type": "IMAGE_QUALITY",
            "signal": signal,
            "severity": "LOW"
        })

    for signal in metadata_result.get("signals", []):
        signals.append({
            "type": "FILE_METADATA",
            "signal": signal,
            "score": metadata_score,
            "severity": "MEDIUM"
        })

    # =====================================================
    # 8. Final result
    # =====================================================

    return {

        "image": {
            "path": str(
                image_path
            )
        },

        "ela": ela_result,

        "noise": noise_result,

        "geometry": geometry_result,

        "metadata": metadata_result,

        "overall": {

            "score": round(
                overall_score,
                2
            ),

            "tampering_score": round(
                overall_score,
                2
            ),

            "quality_score": float(capture_quality.get("score", 100 - geometry_score)),

            "quality_risk_score": round(geometry_score, 2),

            "capture_quality": capture_quality,

            "risk_level": risk_level,

            "signals": signals
        },

        "limitations": [
            "Forensic signals are heuristic and do not prove authenticity",
            "No adverse signal does not prove that an image is unedited",
            "Issuer-signed data should be verified when available",
        ],
    }


# =========================================================
# Standalone execution
# =========================================================

if __name__ == "__main__":

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python forensic_engine.py "
            "<image_path>"
        )

        sys.exit(1)

    image_path = sys.argv[1]

    result = analyze_image_forensics(
        image_path
    )

    print("=" * 60)
    print("IMAGE FORENSICS ENGINE")
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
    print("IMAGE FORENSICS COMPLETE")
    print("=" * 60)
