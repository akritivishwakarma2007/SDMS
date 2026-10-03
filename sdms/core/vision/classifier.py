"""Challenger pipeline: two-stage architecture.
Stage 1: Detector locates bounding box proposals.
Stage 2: Crop Classifier classifies cropped regions into denomination or non-currency.
"""
from __future__ import annotations
import io
import numpy as np
from PIL import Image
from dataclasses import dataclass

from sdms.core.vision.detector import CLASSES, Detection

DENOM_HUE_RANGES = {
    "10": (10, 25),      # Brown
    "20": (35, 55),      # Green-yellow
    "50": (85, 110),     # Cyan / Light blue
    "100": (125, 155),   # Lavender / Purple
    "200": (15, 30),     # Bright Orange / Yellow
    "500": (0, 180),     # Grey / Low saturation
    "2000": (155, 175),  # Magenta
}


@dataclass
class ClassificationResult:
    label: str
    conf: float
    probabilities: dict[str, float]


class CropClassifier:
    """Keras-powered crop classifier operating on image regions."""
    model_version = "keras-mobilenetv2-v1"

    def __init__(self, temperature: float = 1.0):
        self.temperature = temperature

    def classify_crop(self, crop: Image.Image) -> ClassificationResult:
        from sdms.core.vision.classifier_keras import classify
        try:
            res = classify(crop)
            if self.temperature != 1.0 and res.probabilities:
                # Apply temperature scaling if requested
                vals = np.array([res.probabilities.get(c, 1e-5) for c in CLASSES])
                log_vals = np.log(np.clip(vals, 1e-6, 1.0)) / self.temperature
                exp_vals = np.exp(log_vals - np.max(log_vals))
                probs = exp_vals / np.sum(exp_vals)
                best_idx = int(np.argmax(probs))
                return ClassificationResult(
                    label=CLASSES[best_idx],
                    conf=float(probs[best_idx]),
                    probabilities={c: float(p) for c, p in zip(CLASSES, probs)},
                )
            return ClassificationResult(
                label=res.label,
                conf=res.conf,
                probabilities=res.probabilities,
            )
        except Exception:
            return ClassificationResult(
                label="non_currency",
                conf=0.70,
                probabilities={"non_currency": 0.70},
            )


class TwoStagePipeline:
    """Challenger pipeline: Detector for localization + CropClassifier for refinement."""
    model_version = "challenger-twostage-v1"

    def __init__(self, detector, classifier: CropClassifier | None = None):
        self.detector = detector
        self.classifier = classifier or CropClassifier()

    def detect(self, frame) -> list[Detection]:
        # Stage 1: Proposals from base detector
        proposals = self.detector.detect(frame)
        if not proposals:
            return []

        try:
            full_img = Image.open(io.BytesIO(frame.data)).convert("RGB")
        except Exception:
            return proposals

        refined = []
        for prop in proposals:
            x1, y1, x2, y2 = [int(v) for v in prop.bbox]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(full_img.width, x2), min(full_img.height, y2)
            if x2 <= x1 or y2 <= y1:
                refined.append(prop)
                continue

            crop = full_img.crop((x1, y1, x2, y2))
            cls_res = self.classifier.classify_crop(crop)

            # Combined confidence
            final_conf = (prop.conf * 0.4) + (cls_res.conf * 0.6)
            refined.append(Detection(label=cls_res.label, conf=float(final_conf), bbox=prop.bbox))

        return refined
