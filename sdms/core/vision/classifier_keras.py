"""Keras-based Stage-2 banknote classifier for SDMS.

Classifies cropped banknote image regions into Indian currency denominations or non-currency.
Uses a trained MobileNetV2 Keras model (`currency_model_final.keras`).
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import NamedTuple, Union
import numpy as np

# Ensure PyTorch backend for Keras 3 if not already set
if "KERAS_BACKEND" not in os.environ:
    os.environ["KERAS_BACKEND"] = "torch"

import keras

# 8 Output classes corresponding to model's softmax head
CLASSES = ["10", "100", "20", "200", "2000", "50", "500", "Background"]

DEFAULT_MODEL_PATH = os.getenv("SDMS_MODEL_PATH", "currency_model_final.keras")

_MODEL = None


class ClassificationResult:
    """Classification output supporting both tuple unpacking (label, conf) and attribute access."""

    def __init__(self, label: str, conf: float, probabilities: dict[str, float] | None = None):
        self.label = str(label)
        self.conf = float(conf)
        self.probabilities = probabilities or {}

    def __iter__(self):
        yield self.label
        yield self.conf

    def __getitem__(self, index: int):
        if index == 0:
            return self.label
        elif index == 1:
            return self.conf
        elif index == 2:
            return self.probabilities
        raise IndexError("ClassificationResult index out of range (0..2)")

    def __len__(self) -> int:
        return 2

    def __repr__(self) -> str:
        return f"ClassificationResult(label={self.label!r}, conf={self.conf:.4f})"


def _find_model_path(path: str = DEFAULT_MODEL_PATH) -> str:
    """Resolve model path against common relative and workspace locations."""
    candidates = [
        Path(path),
        Path("sdms/models") / Path(path).name,
        Path(__file__).resolve().parents[3] / Path(path).name,
        Path(__file__).resolve().parents[2] / "models" / Path(path).name,
    ]
    for c in candidates:
        if c.exists():
            return str(c.resolve())
    return path


def get_model(model_path: str | None = None) -> keras.Model:
    """Retrieve or load cached Keras classifier model."""
    global _MODEL
    if _MODEL is None or model_path is not None:
        target = _find_model_path(model_path or DEFAULT_MODEL_PATH)
        if not os.path.exists(target):
            raise FileNotFoundError(f"Keras currency model not found at: {target}")
        _MODEL = keras.models.load_model(target)
    return _MODEL


def classify(crop: Union[np.ndarray, "PIL.Image.Image"]) -> ClassificationResult:
    """Classifies a cropped banknote region.

    Args:
        crop: Crop as numpy array (OpenCV BGR/RGB) or PIL Image.

    Returns:
        ClassificationResult(label, conf, probabilities) which can also be unpacked as (label, conf).
    """
    model = get_model()

    # Preprocessing: convert crop to RGB numpy ndarray
    if hasattr(crop, "convert"):  # PIL Image
        img_rgb = np.array(crop.convert("RGB"))
    elif isinstance(crop, np.ndarray):
        if len(crop.shape) == 2:  # Grayscale
            import cv2
            img_rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
        elif crop.shape[2] == 4:  # RGBA
            import cv2
            img_rgb = cv2.cvtColor(crop, cv2.COLOR_RGBA2RGB)
        elif crop.shape[2] == 3:  # OpenCV default is BGR
            import cv2
            img_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        else:
            img_rgb = crop
    else:
        raise TypeError(f"Unsupported crop input type: {type(crop)}")

    import cv2
    resized = cv2.resize(img_rgb, (224, 224))
    # Float32 in range [0, 255] - internal model Rescaling layer handles scale and offset
    batch = np.expand_dims(resized.astype(np.float32), axis=0)

    preds = model.predict(batch, verbose=0)[0]
    pred_idx = int(np.argmax(preds))
    pred_conf = float(preds[pred_idx])

    raw_label = CLASSES[pred_idx]
    label = "non_currency" if raw_label.lower() in ("background", "non_currency") else raw_label

    prob_dict = {
        ("non_currency" if c.lower() in ("background", "non_currency") else c): float(p)
        for c, p in zip(CLASSES, preds)
    }

    return ClassificationResult(
        label=label,
        conf=pred_conf,
        probabilities=prob_dict,
    )
