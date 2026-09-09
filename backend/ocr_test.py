from pathlib import Path
import json
import easyocr

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_PATH = PROJECT_ROOT / "datasets" / "raw" / "passport_001.jpg"
OUTPUT_FOLDER = PROJECT_ROOT / "datasets" / "processed"

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

print("Loading EasyOCR model...")

# Initialize EasyOCR reader (loads English by default)
# Set gpu=True if you have CUDA installed, otherwise gpu=False
reader = easyocr.Reader(['en'], gpu=False)

print(f"Scanning document: {IMAGE_PATH}\n")

# Run OCR detection & recognition
# detail=1 returns bounding box, text, and confidence score
results = reader.readtext(str(IMAGE_PATH), detail=1)

all_text = []

for bbox, text, score in results:
    # Convert numpy coordinate points to standard Python float list
    # Format: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    formatted_bbox = [[float(pt[0]), float(pt[1])] for pt in bbox]

    all_text.append({
        "text": text,
        "confidence": float(score),
        "bbox": formatted_bbox
    })

# Sort extracted entries top-to-bottom by y-coordinate (ensures MRZ lines aren't scrambled)
all_text.sort(key=lambda item: item["bbox"][0][1])

print("========== EXTRACTED TEXT ==========\n")

for item in all_text:
    print(f"{item['text']}   ({item['confidence']:.2f})")

# Save structured output for analyzer.py
output_path = OUTPUT_FOLDER / "ocr_text.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(all_text, f, indent=4)

print(f"\nOCR Complete ✅ ({len(all_text)} lines extracted)")
print(f"Saved to: {output_path}")