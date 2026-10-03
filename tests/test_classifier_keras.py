import numpy as np
from PIL import Image
import pytest

from sdms.core.vision.classifier_keras import classify, ClassificationResult, CLASSES
from sdms.core.vision.detector import NeuralCurrencyDetector
from sdms.core.sources.interfaces import Frame


def test_classify_crop_ndarray():
    # Dummy RGB crop
    dummy = np.zeros((100, 150, 3), dtype=np.uint8)
    res = classify(dummy)
    assert isinstance(res, ClassificationResult)
    assert res.label in ("10", "20", "50", "100", "200", "500", "2000", "non_currency")
    assert 0.0 <= res.conf <= 1.0
    # Test tuple unpacking
    lbl, conf = classify(dummy)
    assert lbl == res.label
    assert conf == res.conf


def test_classify_crop_pil():
    img = Image.new("RGB", (200, 100), color=(180, 175, 170))
    res = classify(img)
    assert res.label in ("10", "20", "50", "100", "200", "500", "2000", "non_currency")
    assert 0.0 <= res.conf <= 1.0


def test_neural_currency_detector_integration():
    detector = NeuralCurrencyDetector()
    assert detector.is_trained_model_loaded()
    assert detector.model_version == "mobilenetv2-keras-currency-v1"

    # Test with dummy frame
    import cv2
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    frame = Frame(buf.tobytes(), trigger_id="test_001")
    dets = detector.detect(frame)
    assert isinstance(dets, list)
