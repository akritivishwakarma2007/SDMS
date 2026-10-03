"""Session-grouped train/val/test split. Photos from one capture session never cross splits.

Expected layout:  data/raw/<session_id>/<image>.jpg  (+ YOLO label .txt next to each image)
Usage: python -m sdms.eval.split data/raw --out data/splits.json --seed 42
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path

IMG = {".jpg", ".jpeg", ".png"}


def session_split(root: Path, seed: int = 42, ratios=(0.7, 0.15, 0.15)) -> dict:
    sessions = sorted(p for p in root.iterdir() if p.is_dir())
    random.Random(seed).shuffle(sessions)
    n = len(sessions)
    a, b = round(n * ratios[0]), round(n * (ratios[0] + ratios[1]))
    if n >= 3:                                   # guarantee every split gets at least one session
        a, b = max(1, min(a, n - 2)), max(min(b, n - 1), min(a, n - 2) + 1)
    groups = {"train": sessions[:a], "val": sessions[a:b], "test": sessions[b:]}
    return {k: sorted(str(f) for s in v for f in s.iterdir() if f.suffix.lower() in IMG) for k, v in groups.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--out", default="data/splits.json")
    ap.add_argument("--seed", type=int, default=42); a = ap.parse_args()
    sp = session_split(Path(a.root), a.seed)
    Path(a.out).write_text(json.dumps(sp, indent=1))
    print({k: len(v) for k, v in sp.items()})
