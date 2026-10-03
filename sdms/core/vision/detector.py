"""Detector interface + implementations.

Implementations:
- YoloDetector: Wraps ultralytics YOLO (.pt or .onnx).
- ColorFeatureDetector: Lightweight computer vision detector using OpenCV color segmentation & contours.
- MockDetector: Reads ground truth from frame.meta and applies configurable noise (for fast tests/sim).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import os
import json
import random
import numpy as np

from sdms.core.sources.interfaces import Frame

CLASSES = ["10", "20", "50", "100", "200", "500", "2000", "non_currency"]


@dataclass(frozen=True)
class Detection:
    label: str                     # one of CLASSES
    conf: float
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2

    @property
    def denom(self) -> int | None:
        return int(self.label) if self.label.isdigit() else None


class Detector(Protocol):
    model_version: str
    def detect(self, frame: Frame) -> list[Detection]: ...


class NeuralCurrencyDetector:
    """Production Deep Learning Detector for Indian Currency.
    
    Uses Stage-1 contour proposal localization combined with Stage-2 Keras MobileNetV2
    classifier (`currency_model_final.keras`) to predict banknote denominations on
    candidate regions and live camera frames.
    Maps predictions to classes: '10', '20', '50', '100', '200', '500', '2000', 'non_currency'.
    """
    model_version = "mobilenetv2-keras-currency-v1"

    def __init__(
        self,
        model_path: str = "currency_model_final.keras",
        conf_floor: float = 0.20,
    ):
        self.conf_floor = conf_floor
        self.model_path = model_path
        # Pre-warm or check model availability
        from sdms.core.vision.classifier_keras import get_model
        try:
            get_model(model_path)
            self._model_loaded = True
        except Exception:
            self._model_loaded = False
        self._fallback = ColorFeatureDetector(conf_floor=conf_floor) if not self._model_loaded else None

    def is_trained_model_loaded(self) -> bool:
        return self._model_loaded

    def _predict_roi(self, roi_img) -> tuple[str, float]:
        from sdms.core.vision.classifier_keras import classify
        try:
            res = classify(roi_img)
            return res.label, res.conf
        except Exception:
            return "non_currency", 0.0

    def detect(self, frame: Frame) -> list[Detection]:
        # If no neural weights present, use fallback
        if not self.is_trained_model_loaded():
            return self._fallback.detect(frame)

        import cv2
        img = cv2.imdecode(np.frombuffer(frame.data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        detections = []
        min_area = (w * h) * 0.03
        max_area = (w * h) * 0.95

        found_candidate = False
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue

            x, y, cw, ch = cv2.boundingRect(cnt)
            x1, y1 = max(0, x - 6), max(0, y - 6)
            x2, y2 = min(w, x + cw + 6), min(h, y + ch + 6)
            roi = img[y1:y2, x1:x2]
            if roi.size == 0:
                continue

            found_candidate = True
            lbl, conf = self._predict_roi(roi)
            if conf >= self.conf_floor:
                detections.append(Detection(label=lbl, conf=conf, bbox=(float(x1), float(y1), float(x2), float(y2))))

        # If no isolated contour, classify the central frame
        if not found_candidate or len(detections) == 0:
            lbl, conf = self._predict_roi(img)
            inset_x, inset_y = int(w * 0.08), int(h * 0.12)
            detections.append(Detection(label=lbl, conf=conf, bbox=(float(inset_x), float(inset_y), float(w - inset_x), float(h - inset_y))))

        return detections


class YoloDetector:
    """Wraps ultralytics YOLO (.pt or .onnx)."""
    def __init__(self, weights: str, model_version: str = "yolov8n-v0", conf_floor: float = 0.05):
        from ultralytics import YOLO   # lazy import
        self.model = YOLO(weights)
        self.model_version = model_version
        self.conf_floor = conf_floor

    def detect(self, frame: Frame) -> list[Detection]:
        import cv2
        img = cv2.imdecode(np.frombuffer(frame.data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        res = self.model.predict(img, conf=self.conf_floor, verbose=False)[0]
        names = res.names
        out = []
        for b in res.boxes:
            cls_idx = int(b.cls)
            lbl = names[cls_idx] if cls_idx in names else str(cls_idx)
            out.append(Detection(lbl, float(b.conf), tuple(map(float, b.xyxy[0].tolist()))))
        return out


class ColorFeatureDetector:
    """Standalone CV detector extracting candidate contours and classifying by color profile & aspect ratio."""
    model_version = "cv-color-v1"

    def __init__(self, conf_floor: float = 0.20):
        self.conf_floor = conf_floor

    def detect(self, frame: Frame) -> list[Detection]:
        import cv2
        img = cv2.imdecode(np.frombuffer(frame.data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 30, 150)

        # Morphological close to bridge contours
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections = []

        min_area = (w * h) * 0.02
        max_area = (w * h) * 0.85

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue

            x, y, cw, ch = cv2.boundingRect(cnt)
            # Expand slightly
            x1, y1 = max(0, x - 5), max(0, y - 5)
            x2, y2 = min(w, x + cw + 5), min(h, y + ch + 5)
            bw, bh = x2 - x1, y2 - y1
            aspect = max(bw, bh) / max(1, min(bw, bh))

            roi = img[y1:y2, x1:x2]
            if roi.size == 0:
                continue

            # Color analysis in HSV
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            mean_h, mean_s, mean_v = cv2.mean(hsv)[:3]
            mean_b, mean_g, mean_r = cv2.mean(roi)[:3]

            # Classification logic
            lbl = "non_currency"
            conf = 0.75

            if mean_s < 35 and mean_v > 180:
                # White paper / receipt
                lbl = "non_currency"
                conf = 0.95
            elif mean_s < 45 and 70 < mean_v < 150:
                # ₹500 Stone grey
                lbl = "500"
                conf = 0.93
            elif mean_b > mean_r + 30 and mean_g > 110:
                # ₹50 Fluorescent blue
                lbl = "50"
                conf = 0.94
            elif mean_b > 130 and mean_r > 120 and mean_g < 160:
                # ₹100 Lavender
                lbl = "100"
                conf = 0.92
            elif mean_r > 170 and mean_b > 100 and mean_g < 80:
                # ₹2000 Magenta
                lbl = "2000"
                conf = 0.94
            elif mean_r > 180 and mean_g > 120 and mean_b < 110:
                # ₹200 Bright yellow
                lbl = "200"
                conf = 0.91
            elif mean_g > mean_r and mean_g > 130 and mean_b < 90:
                # ₹20 Greenish yellow
                lbl = "20"
                conf = 0.90
            elif mean_r > 120 and mean_g < 100 and mean_b < 75:
                # ₹10 Chocolate brown
                lbl = "10"
                conf = 0.89
            else:
                lbl = "non_currency"
                conf = 0.65

            # If aspect ratio is close to Indian currency (1.8 - 2.5), boost confidence
            if 1.7 <= aspect <= 2.6 and lbl != "non_currency":
                conf = min(0.99, conf + 0.05)

            if conf >= self.conf_floor:
                detections.append(Detection(label=lbl, conf=round(conf, 4), bbox=(float(x1), float(y1), float(x2), float(y2))))

        return detections


class MockDetector:
    """Reads ground truth from frame.meta and applies configurable noise. For simulator/tests only."""
    model_version = "mock-v0"

    def __init__(self, seed: int = 0, base_conf: float = 0.96, confusion_rate: float = 0.02):
        self.rng = random.Random(seed)
        self.base_conf = base_conf
        self.confusion_rate = confusion_rate

    def detect(self, frame: Frame) -> list[Detection]:
        truth = frame.meta.get("truth", [])
        quality = frame.meta.get("quality", "ok")
        out = []
        for i, label in enumerate(truth):
            conf = min(0.999, max(0.05, self.rng.gauss(self.base_conf, 0.03)))
            if quality in ("blur", "dark"):
                conf = max(0.05, conf - self.rng.uniform(0.25, 0.6))
            shown = label
            if label != "non_currency" and self.rng.random() < self.confusion_rate:
                shown = self.rng.choice([c for c in CLASSES if c not in (label, "non_currency")])
                conf = max(0.05, conf - self.rng.uniform(0.1, 0.5))
            x = 20 + i * 330
            bbox = (x, 30, x + 300, 30 + 300 / 2.1)
            if label == "non_currency":
                conf = min(conf, self.rng.uniform(0.3, 0.95))
            out.append(Detection(shown, conf, bbox))
        return out
