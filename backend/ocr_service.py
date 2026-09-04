from pathlib import Path
from threading import RLock

import cv2

from .config import settings


class OCRService:
    """Lazily load one EasyOCR reader and serialize model inference."""

    def __init__(self):
        self._reader = None
        self._rapid_reader = None
        self._lock = RLock()

    def _get_rapid_reader(self):
        if self._rapid_reader is None:
            from rapidocr import RapidOCR

            self._rapid_reader = RapidOCR()
        return self._rapid_reader

    def _get_reader(self):
        if self._reader is None:
            import easyocr

            settings.easyocr_model_directory.mkdir(parents=True, exist_ok=True)
            self._reader = easyocr.Reader(
                ["en"],
                gpu=False,
                model_storage_directory=str(settings.easyocr_model_directory),
                verbose=False,
            )
        return self._reader

    def warmup(self) -> dict:
        """Load OCR weights before the user submits the first document."""
        with self._lock:
            try:
                self._get_rapid_reader()
                engine = "rapidocr"
            except (ImportError, ModuleNotFoundError):
                self._get_reader()
                engine = "easyocr"
        return {"ready": True, "engine": engine}

    def extract(self, image_path: str | Path) -> list[dict]:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Unable to read OCR image: {image_path}")

        # EasyOCR's default 2560px canvas is expensive on CPU and unnecessary
        # for typical card photos. Keep enough resolution for small Aadhaar text
        # while reducing detector latency and memory use on phone images.
        height, width = image.shape[:2]
        max_dimension = max(height, width)
        if max_dimension > settings.analysis_max_dimension:
            scale = settings.analysis_max_dimension / max_dimension
            image = cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        try:
            with self._lock:
                # Identity documents are captured upright by the UI. Skipping
                # per-line direction classification removes one neural pass.
                rapid_result = self._get_rapid_reader()(image, use_cls=False)
            results = [] if not rapid_result else zip(
                rapid_result.boxes,
                rapid_result.txts,
                rapid_result.scores,
            )
        except (ImportError, ModuleNotFoundError):
            # Keep existing installations functional until dependencies are
            # refreshed; new environments use the substantially faster ONNX
            # engine declared in requirements.txt.
            with self._lock:
                results = self._get_reader().readtext(
                    image,
                    detail=1,
                    decoder="greedy",
                    batch_size=16,
                    workers=0,
                    canvas_size=settings.analysis_max_dimension,
                    mag_ratio=1.0,
                )

        items = []
        for bbox, text, confidence in results:
            items.append({
                "text": str(text),
                "confidence": float(confidence),
                "bbox": [
                    [float(point[0]), float(point[1])]
                    for point in bbox
                ],
            })

        items.sort(key=lambda item: item["bbox"][0][1])
        return items


ocr_service = OCRService()
