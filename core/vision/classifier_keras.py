"""Proxy module exposing sdms.core.vision.classifier_keras at core.vision.classifier_keras."""
from sdms.core.vision.classifier_keras import (
    classify,
    get_model,
    ClassificationResult,
    CLASSES,
    DEFAULT_MODEL_PATH,
)

__all__ = ["classify", "get_model", "ClassificationResult", "CLASSES", "DEFAULT_MODEL_PATH"]
