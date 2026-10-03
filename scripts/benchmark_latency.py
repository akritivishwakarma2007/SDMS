"""Latency benchmarking script for SDMS inference pipelines.
Measures p50, p95, p99 latency and frames-per-second (FPS) on CPU across 100 runs.
Can be rerun on a Raspberry Pi or target edge device.
"""
from __future__ import annotations
import io
import time
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image

from sdms.core.sources.interfaces import Frame
from sdms.core.vision.detector import ColorFeatureDetector
from sdms.core.vision.classifier import TwoStagePipeline, CropClassifier


def benchmark(detector, dummy_frame: Frame, n_iterations: int = 100) -> dict:
    # Warmup
    for _ in range(5):
        detector.detect(dummy_frame)

    latencies = []
    for _ in range(n_iterations):
        t0 = time.perf_counter()
        detector.detect(dummy_frame)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)  # ms

    latencies.sort()
    p50 = np.percentile(latencies, 50)
    p95 = np.percentile(latencies, 95)
    p99 = np.percentile(latencies, 99)
    mean_lat = np.mean(latencies)
    fps = 1000.0 / mean_lat if mean_lat > 0 else float("inf")

    return {
        "model": getattr(detector, "model_version", "unknown"),
        "iterations": n_iterations,
        "mean_ms": round(float(mean_lat), 2),
        "p50_ms": round(float(p50), 2),
        "p95_ms": round(float(p95), 2),
        "p99_ms": round(float(p99), 2),
        "fps": round(float(fps), 1),
    }


def main():
    # Create synthetic test frame
    img = Image.new("RGB", (640, 480), color=(230, 225, 215))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    frame = Frame(buf.getvalue(), trigger_id="bench-001")

    baseline = ColorFeatureDetector()
    challenger = TwoStagePipeline(ColorFeatureDetector(), CropClassifier())

    print(f"Benchmarking CPU inference latency over 100 iterations per model...\n")
    res_b = benchmark(baseline, frame)
    res_c = benchmark(challenger, frame)

    print("# SDMS Inference Latency Benchmark")
    print(f"| Model | Mean (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (FPS) |")
    print(f"|---|:---:|:---:|:---:|:---:|:---:|")
    print(f"| Baseline ({res_b['model']}) | {res_b['mean_ms']} | {res_b['p50_ms']} | {res_b['p95_ms']} | {res_b['p99_ms']} | **{res_b['fps']} FPS** |")
    print(f"| Challenger ({res_c['model']}) | {res_c['mean_ms']} | {res_c['p50_ms']} | {res_c['p95_ms']} | {res_c['p99_ms']} | **{res_c['fps']} FPS** |")
    print("\n_Benchmarked on local CPU. Ready for rerun on Raspberry Pi / edge deployment._")


if __name__ == "__main__":
    main()
