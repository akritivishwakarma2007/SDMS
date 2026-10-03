"""Dataset generator for SDMS: generates realistic synthetic banknote images and YOLO annotations.

Creates session-grouped directories under data/raw/ and generates data/splits.json.
Classes:
  0: 10
  1: 20
  2: 50
  3: 100
  4: 200
  5: 500
  6: 2000
  7: non_currency
"""
from __future__ import annotations
import argparse
import json
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from sdms.core.vision.detector import CLASSES
from sdms.eval.split import session_split

DENOM_COLORS = {
    "10": (160, 82, 45),       # Chocolate brown
    "20": (173, 190, 48),      # Greenish yellow
    "50": (0, 180, 216),       # Fluorescent cyan/blue
    "100": (165, 148, 249),    # Lavender
    "200": (244, 162, 97),     # Bright orange/yellow
    "500": (108, 117, 125),    # Stone grey
    "2000": (214, 51, 132),    # Magenta
}

BG_COLORS = [
    (240, 235, 225),  # light wood/cream desk
    (220, 220, 225),  # metal/plastic tray
    (70, 50, 35),     # dark wood
    (180, 180, 180),  # neutral counter
    (40, 40, 45),     # dim shadow backdrop
]


def render_note(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int], denom: str, angle: float = 0.0):
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    color = DENOM_COLORS.get(denom, (120, 120, 120))
    border_color = tuple(max(0, c - 40) for c in color)

    # Note base
    draw.rectangle([x1, y1, x2, y2], fill=color, outline=border_color, width=3)

    # Inner decorative border
    draw.rectangle([x1 + 6, y1 + 6, x2 - 6, y2 - 6], outline=(255, 255, 255), width=1)

    # Watermark oval
    wm_w, wm_h = int(w * 0.22), int(h * 0.65)
    wm_x = x1 + int(w * 0.1)
    wm_y = y1 + int((h - wm_h) / 2)
    wm_color = tuple(min(255, c + 25) for c in color)
    draw.ellipse([wm_x, wm_y, wm_x + wm_w, wm_y + wm_h], fill=wm_color, outline=border_color)

    # Central denomination text
    cx, cy = x1 + int(w * 0.55), y1 + int(h * 0.45)
    draw.text((cx, cy), f"Rs {denom}", fill=(255, 255, 255), anchor="mm")
    draw.text((x1 + 15, y1 + 15), denom, fill=(255, 255, 255))
    draw.text((x2 - 35, y2 - 25), denom, fill=(255, 255, 255))
    # Security strip representation
    sec_x = x1 + int(w * 0.38)
    draw.line([(sec_x, y1 + 4), (sec_x, y2 - 4)], fill=(180, 200, 70), width=3)


def render_negative(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int], kind: str):
    x1, y1, x2, y2 = bbox
    if kind == "receipt":
        draw.rectangle([x1, y1, x2, y2], fill=(250, 250, 250), outline=(180, 180, 180), width=1)
        for ly in range(y1 + 10, y2 - 10, 12):
            draw.line([(x1 + 8, ly), (x2 - 8, ly)], fill=(120, 120, 120), width=1)
    elif kind == "envelope":
        draw.rectangle([x1, y1, x2, y2], fill=(230, 215, 185), outline=(170, 150, 120), width=2)
        draw.line([(x1, y1), ((x1 + x2) // 2, (y1 + y2) // 2)], fill=(170, 150, 120), width=2)
        draw.line([(x2, y1), ((x1 + x2) // 2, (y1 + y2) // 2)], fill=(170, 150, 120), width=2)
    else:  # plain paper
        draw.rectangle([x1, y1, x2, y2], fill=(245, 245, 245), outline=(200, 200, 200), width=1)


def generate_synthetic_dataset(output_root: Path, n_per_session: int = 25, seed: int = 42):
    rng = random.Random(seed)
    output_root.mkdir(parents=True, exist_ok=True)

    sessions = [
        ("session_01_bright_desk", (235, 230, 220), False),
        ("session_02_dim_evening", (60, 55, 55), True),
        ("session_03_wood_counter", (120, 80, 50), False),
        ("session_04_folded_drops", (200, 205, 210), False),
        ("session_05_multi_notes", (210, 210, 210), False),
        ("session_06_negatives", (180, 175, 170), False),
    ]

    all_denoms = ["10", "20", "50", "100", "200", "500", "2000"]
    img_w, img_h = 640, 480

    for sess_name, bg_color, is_dim in sessions:
        sess_dir = output_root / sess_name
        sess_dir.mkdir(parents=True, exist_ok=True)

        for idx in range(1, n_per_session + 1):
            img = Image.new("RGB", (img_w, img_h), color=bg_color)
            draw = ImageDraw.Draw(img)
            annotations = []

            if sess_name == "session_06_negatives":
                # Only negative samples or blank frame
                if rng.random() > 0.15:
                    nw = rng.randint(120, 240)
                    nh = rng.randint(80, 180)
                    nx1 = rng.randint(50, img_w - nw - 50)
                    ny1 = rng.randint(50, img_h - nh - 50)
                    kind = rng.choice(["receipt", "envelope", "paper"])
                    render_negative(draw, (nx1, ny1, nx1 + nw, ny1 + nh), kind)
                    # Non-currency annotation
                    cls_id = CLASSES.index("non_currency")
                    xc = (nx1 + nw / 2) / img_w
                    yc = (ny1 + nh / 2) / img_h
                    annotations.append(f"{cls_id} {xc:.6f} {yc:.6f} {nw/img_w:.6f} {nh/img_h:.6f}")
            elif sess_name == "session_05_multi_notes":
                # Multiple notes in the frame
                k = rng.choice([2, 3])
                for j in range(k):
                    d = rng.choice(all_denoms)
                    aspect = rng.uniform(1.8, 2.3)
                    nw = rng.randint(220, 280)
                    nh = int(nw / aspect)
                    nx1 = 30 + j * 190 + rng.randint(-15, 15)
                    ny1 = rng.randint(60, img_h - nh - 60)
                    nx2 = min(img_w - 10, nx1 + nw)
                    ny2 = min(img_h - 10, ny1 + nh)
                    render_note(draw, (nx1, ny1, nx2, ny2), d)
                    cls_id = CLASSES.index(d)
                    actual_w = nx2 - nx1
                    actual_h = ny2 - ny1
                    xc = (nx1 + actual_w / 2) / img_w
                    yc = (ny1 + actual_h / 2) / img_h
                    annotations.append(f"{cls_id} {xc:.6f} {yc:.6f} {actual_w/img_w:.6f} {actual_h/img_h:.6f}")
            else:
                # 1 note, occasionally 2
                k = 2 if (rng.random() < 0.25 and sess_name != "session_04_folded_drops") else 1
                for j in range(k):
                    d = rng.choice(all_denoms)
                    aspect = rng.uniform(1.4, 2.1) if sess_name == "session_04_folded_drops" else rng.uniform(1.8, 2.4)
                    nw = rng.randint(240, 320)
                    nh = int(nw / aspect)
                    nx1 = rng.randint(40 + j * 120, min(img_w - nw - 20, 300 + j * 100))
                    ny1 = rng.randint(50, img_h - nh - 50)
                    nx2 = nx1 + nw
                    ny2 = ny1 + nh
                    render_note(draw, (nx1, ny1, nx2, ny2), d)
                    cls_id = CLASSES.index(d)
                    xc = (nx1 + nw / 2) / img_w
                    yc = (ny1 + nh / 2) / img_h
                    annotations.append(f"{cls_id} {xc:.6f} {yc:.6f} {nw/img_w:.6f} {nh/img_h:.6f}")

            # Dimming or blur effect for realistic drops
            if is_dim:
                img = img.point(lambda p: int(p * 0.65))
            if rng.random() < 0.15:
                img = img.filter(ImageFilter.GaussianBlur(radius=1.2))

            img_path = sess_dir / f"IMG_{idx:04d}.jpg"
            lbl_path = sess_dir / f"IMG_{idx:04d}.txt"

            img.save(img_path, format="JPEG", quality=90)
            lbl_path.write_text("\n".join(annotations))

    print(f"Generated {len(sessions)} sessions with {n_per_session} images each under {output_root}")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic dataset and splits.")
    parser.add_argument("--out", default="data/raw", help="Output directory for raw data")
    parser.add_argument("--splits-out", default="data/splits.json", help="Output path for splits.json")
    parser.add_argument("--n-per-session", type=int, default=30, help="Images per session")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    raw_path = Path(args.out)
    generate_synthetic_dataset(raw_path, n_per_session=args.n_per_session, seed=args.seed)

    splits = session_split(raw_path, seed=args.seed)
    Path(args.splits_out).write_text(json.dumps(splits, indent=2))
    print(f"Created session-grouped splits: {{k: len(v) for k, v in splits.items()}}")
    print(f"Splits saved to {args.splits_out}")


if __name__ == "__main__":
    main()
