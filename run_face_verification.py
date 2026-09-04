import argparse
import json
import sys

from ai.face_verification.verifier import IdentityVerifier


def main():
    parser = argparse.ArgumentParser(
        description="Live identity face verification"
    )

    parser.add_argument(
        "--id-image",
        required=True,
        help="Path to the uploaded ID/passport image",
    )

    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Webcam index (default: 0)",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.40,
        help="SFace cosine similarity threshold",
    )

    args = parser.parse_args()

    try:
        verifier = IdentityVerifier(
            match_threshold=args.threshold
        )

        result = verifier.run_webcam_verification(
            id_image_path=args.id_image,
            camera_index=args.camera,
        )

    except Exception as exc:
        result = {
            "verification_passed": False,
            "error": str(exc),
        }

    print("\n" + "=" * 60)
    print("FACE VERIFICATION RESULT")
    print("=" * 60)

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    sys.exit(
        0 if result.get("verification_passed") else 1
    )


if __name__ == "__main__":
    main()