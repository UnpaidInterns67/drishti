"""Generate a synthetic passport image and smoke-test EasyOCR."""

import json
import tempfile
from pathlib import Path

import easyocr
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIRECTORY = PROJECT_ROOT / "venv" / "easyocr_models"


def main():
    with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "venv") as directory:
        image_path = Path(directory) / "mock_passport.png"
        image = Image.new("RGB", (1400, 700), "white")
        draw = ImageDraw.Draw(image)
        heading = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 52)
        body = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 42)
        mono = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 34)

        draw.rectangle((15, 15, 1385, 685), outline="navy", width=5)
        draw.text((60, 50), "PASSPORT", fill="navy", font=heading)
        draw.text((60, 150), "Name: JANE ALICE DOE", fill="black", font=body)
        draw.text((60, 225), "Passport No: A1234567", fill="black", font=body)
        draw.text((60, 300), "Nationality: IND", fill="black", font=body)
        draw.text((60, 375), "Date of Birth: 01/01/1990", fill="black", font=body)
        draw.text((60, 500), "P<INDDOE<<JANE<ALICE<<<<<<<<<<<<<<<<<<<<", fill="black", font=mono)
        image.save(image_path)

        reader = easyocr.Reader(
            ["en"],
            gpu=False,
            model_storage_directory=str(MODEL_DIRECTORY),
            verbose=False,
        )
        detected = reader.readtext(str(image_path), detail=0)

    normalized = " ".join(detected).upper().replace(" ", "")
    checks = {
        "passport_heading": "PASSPORT" in normalized,
        "document_number": "A1234567" in normalized,
        "holder_name": "JANE" in normalized and "DOE" in normalized,
    }
    result = {"detected_text": detected, "checks": checks}
    print(json.dumps(result, indent=2))

    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
