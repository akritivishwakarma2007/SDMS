"""Decision policy: every detection ends as ACCEPT, REVIEW or REJECT. Never count what you're unsure of."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from sdms.core.vision.detector import Detection

ACCEPT, REVIEW, REJECT = "ACCEPT", "REVIEW", "REJECT"


@dataclass
class PolicyConfig:
    # Placeholder values. Real per-class thresholds come from PR curves on the validation set (Week 4).
    accept_thresholds: dict[str, float] = field(default_factory=lambda: {
        d: 0.85 for d in ["10", "20", "50", "100", "200", "500", "2000"]})
    floor: float = 0.30              # below this: REJECT
    min_ratio: float = 1.3           # bbox long/short side sanity bounds (folds/rotation widen these)
    max_ratio: float = 3.2
    iou_conflict: float = 0.30       # overlapping boxes -> REVIEW
    valid_denoms: tuple[str, ...] = ("10", "20", "50", "100", "200", "500", "2000")

    def as_dict(self) -> dict:
        return asdict(self)


def iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def ratio(b) -> float:
    w, h = b[2]-b[0], b[3]-b[1]
    lo, hi = min(w, h), max(w, h)
    return hi / lo if lo > 0 else float("inf")


def decide_item(d: Detection, cfg: PolicyConfig, overlaps: bool) -> tuple[str, str]:
    """Returns (decision, reason)."""
    if d.denom is None:
        return REJECT, "non_currency"
    if d.label not in cfg.valid_denoms:
        return REJECT, "denomination_not_enabled"
    if d.conf < cfg.floor:
        return REJECT, "below_floor"
    if not (cfg.min_ratio <= ratio(d.bbox) <= cfg.max_ratio):
        return REVIEW, "odd_aspect_ratio"
    if overlaps:
        return REVIEW, "overlap_conflict"
    if d.conf < cfg.accept_thresholds.get(d.label, 1.0):
        return REVIEW, "grey_zone"
    return ACCEPT, "confident"


def decide_frame(dets: list[Detection], cfg: PolicyConfig) -> tuple[str, list[dict]]:
    """Item-level decisions + event-level status.
    Event status: any REVIEW -> REVIEW (nothing counted until a human resolves it);
    else any ACCEPT -> ACCEPT; else REJECT (also for an empty frame)."""
    items = []
    for i, d in enumerate(dets):
        overlaps = any(j != i and o.denom is not None and iou(d.bbox, o.bbox) > cfg.iou_conflict
                       for j, o in enumerate(dets))
        dec, why = decide_item(d, cfg, overlaps)
        items.append({"label": d.label, "conf": round(d.conf, 4),
                      "bbox": [round(v, 1) for v in d.bbox], "decision": dec, "reason": why})
    decisions = {it["decision"] for it in items}
    if REVIEW in decisions:
        status = REVIEW
    elif ACCEPT in decisions:
        status = ACCEPT
    else:
        status = REJECT
    return status, items
