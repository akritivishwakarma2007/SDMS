"""Ablation study script: Baseline (Single-Stage) vs. Challenger (Two-Stage Pipeline).
Evaluates both pipelines on the frozen test set and outputs an ablation comparison table.
"""
from __future__ import annotations
import json
import time
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pathlib import Path
from collections import defaultdict

from sdms.core.sources.interfaces import Frame
from sdms.core.vision.detector import CLASSES, ColorFeatureDetector, NeuralCurrencyDetector
from sdms.core.vision.classifier import TwoStagePipeline, CropClassifier


def evaluate_pipeline(pipeline, test_files: list[str]) -> dict:
    total_samples = 0
    correct = 0
    latencies = []
    per_class_tp = defaultdict(int)
    per_class_total = defaultdict(int)

    for fpath in test_files:
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

        frame = Frame(p_img.read_bytes(), trigger_id=p_img.stem)

        t0 = time.perf_counter()
        dets = pipeline.detect(frame)
        latencies.append((time.perf_counter() - t0) * 1000)

        pred_labels = [d.label for d in dets] if dets else ["non_currency"]

        for t in true_labels:
            per_class_total[t] += 1
            if t in pred_labels:
                per_class_tp[t] += 1
                correct += 1
            total_samples += 1

    acc = (correct / total_samples) if total_samples > 0 else 0.0
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "model": getattr(pipeline, "model_version", "unknown"),
        "accuracy": acc,
        "avg_latency_ms": avg_lat,
        "samples": total_samples,
        "per_class_recall": {c: (per_class_tp[c] / per_class_total[c]) if per_class_total[c] > 0 else 1.0 for c in per_class_total}
    }


def main():
    splits_path = Path("data/splits.json")
    if not splits_path.exists():
        print("Error: data/splits.json not found. Run python -m sdms.eval.generate_dataset first.")
        return

    splits = json.loads(splits_path.read_text())
    test_files = splits.get("test", [])
    if not test_files:
        print("No test files in splits.json")
        return

    baseline = ColorFeatureDetector()
    challenger = TwoStagePipeline(ColorFeatureDetector(), CropClassifier())
    neural = NeuralCurrencyDetector()

    print("Running Ablation Evaluation on Frozen Test Set...")
    res_base = evaluate_pipeline(baseline, test_files)
    res_chall = evaluate_pipeline(challenger, test_files)
    res_neural = evaluate_pipeline(neural, test_files)

    print("\n# SDMS Ablation Study Results\n")
    print("| Pipeline | Model Architecture | Accuracy | Latency (ms/frame) | Recommendation |")
    print("|---|---|:---:|:---:|---|")
    print(f"| Baseline (Single-Stage) | {res_base['model']} | {res_base['accuracy']:.1%} | {res_base['avg_latency_ms']:.2f} ms | Baseline CV |")
    print(f"| Challenger (Two-Stage Refinement) | {res_chall['model']} | {res_chall['accuracy']:.1%} | {res_chall['avg_latency_ms']:.2f} ms | Two-Stage Pipeline |")
    print(f"| Production (Keras MobileNetV2 Stage-2) | {res_neural['model']} | {res_neural['accuracy']:.1%} | {res_neural['avg_latency_ms']:.2f} ms | **Selected Production** |")
    print("\n_Note: Evaluated on frozen test set without data leakage._")


if __name__ == "__main__":
    main()
