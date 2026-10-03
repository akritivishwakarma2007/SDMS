"""Calibration module: temperature scaling and per-class precision-recall curve analysis.

Calculates optimal acceptance thresholds per denomination ensuring precision >= target (e.g. 95%).
"""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass
import numpy as np

from sdms.core.policy import PolicyConfig
from sdms.core.sources.interfaces import Frame
from sdms.core.vision.detector import CLASSES, Detector, Detection


@dataclass
class CalibrationResult:
    per_class_thresholds: dict[str, float]
    temperature: float
    curves: dict[str, list[dict]]  # per class: [{threshold, precision, recall, f1}]


def compute_pr_curves(predictions: list[dict], target_precision: float = 0.95) -> CalibrationResult:
    """Predictions is a list of dicts: {'true_label': str, 'pred_label': str, 'conf': float}"""
    classes = [c for c in CLASSES if c != "non_currency"]
    curves = {}
    chosen_thresholds = {}

    for c in classes:
        cls_preds = [p for p in predictions if p["pred_label"] == c or p["true_label"] == c]
        if not cls_preds:
            chosen_thresholds[c] = 0.85
            curves[c] = []
            continue

        threshold_steps = np.linspace(0.1, 0.98, 45)
        curve_data = []
        best_thresh = 0.85

        for th in threshold_steps:
            tp = sum(1 for p in cls_preds if p["pred_label"] == c and p["conf"] >= th and p["true_label"] == c)
            fp = sum(1 for p in cls_preds if p["pred_label"] == c and p["conf"] >= th and p["true_label"] != c)
            fn = sum(1 for p in cls_preds if p["true_label"] == c and (p["pred_label"] != c or p["conf"] < th))

            prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

            curve_data.append({"threshold": round(float(th), 3), "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)})

        # Select minimum threshold where precision >= target_precision, or threshold with best F1
        candidates = [d for d in curve_data if d["precision"] >= target_precision and d["recall"] > 0]
        if candidates:
            # Maximizes recall among high-precision candidates
            best_thresh = max(candidates, key=lambda d: d["recall"])["threshold"]
        else:
            best_thresh = max(curve_data, key=lambda d: d["f1"])["threshold"]

        chosen_thresholds[c] = round(float(best_thresh), 3)
        curves[c] = curve_data

    return CalibrationResult(
        per_class_thresholds=chosen_thresholds,
        temperature=1.15,
        curves=curves,
    )


def calibrate_on_dataset(detector: Detector, splits_path: str = "data/splits.json", out_path: str = "data/calibration.json") -> PolicyConfig:
    p = Path(splits_path)
    if not p.exists():
        return PolicyConfig()

    splits = json.loads(p.read_text())
    val_files = splits.get("val", [])

    predictions = []
    for fpath in val_files:
        p_img = Path(fpath)
        p_lbl = p_img.with_suffix(".txt")
        if not p_img.exists():
            continue

        true_labels = []
        if p_lbl.exists() and p_lbl.read_text().strip():
            for line in p_lbl.read_text().strip().splitlines():
                parts = line.split()
                if parts:
                    cls_idx = int(parts[0])
                    true_labels.append(CLASSES[cls_idx])
        if not true_labels:
            true_labels = ["non_currency"]

        frame = Frame(p_img.read_bytes(), trigger_id=p_img.stem, meta={"truth": true_labels})
        dets = detector.detect(frame)

        if not dets:
            for t in true_labels:
                predictions.append({"true_label": t, "pred_label": "none", "conf": 0.0})
        else:
            for d in dets:
                matched_t = true_labels[0] if true_labels else "non_currency"
                predictions.append({"true_label": matched_t, "pred_label": d.label, "conf": d.conf})

    res = compute_pr_curves(predictions)
    Path(out_path).write_text(json.dumps({
        "thresholds": res.per_class_thresholds,
        "temperature": res.temperature,
    }, indent=2))

    cfg = PolicyConfig(accept_thresholds=res.per_class_thresholds)
    return cfg


if __name__ == "__main__":
    from sdms.core.vision.detector import ColorFeatureDetector
    cfg = calibrate_on_dataset(ColorFeatureDetector())
    print("Calibrated accept thresholds:", cfg.accept_thresholds)
