"""Multi-note object tracking & stability engine for live camera video feeds.

Solves the duplicate counting problem:
A note visible across dozens of consecutive frames is tracked with a stable tracking ID
and evaluated through a multi-frame stability window:
  DETECTING (1-2 frames) -> STABILIZING (3-4 frames) -> CONFIRMED (>= 5 frames).
Only once a note reaches CONFIRMED is it added to the donation count, and exactly once.
If confidence is in the grey zone or overlaps occur, it flags as REVIEW.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from collections import Counter
from typing import Literal

from sdms.core.vision.detector import Detection
from sdms.core.policy import iou

NoteState = Literal["DETECTING", "STABILIZING", "CONFIRMED", "REVIEW", "REJECT"]


@dataclass
class TrackedNote:
    tracking_id: int
    bbox: tuple[float, float, float, float]
    label: str
    confidence: float
    state: NoteState = "DETECTING"
    frames_seen: int = 1
    frames_missing: int = 0
    counted: bool = False
    label_history: list[str] = field(default_factory=list)
    conf_history: list[float] = field(default_factory=list)

    @property
    def centroid(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def denomination(self) -> int | None:
        return int(self.label) if self.label.isdigit() else None


class NoteTracker:
    """Tracks physical notes across consecutive video frames to prevent duplicate counts."""

    def __init__(
        self,
        iou_threshold: float = 0.35,
        max_missing_frames: int = 8,
        stabilize_frames: int = 3,
        confirm_frames: int = 5,
        confirm_confidence: float = 0.80,
    ):
        self.iou_threshold = iou_threshold
        self.max_missing_frames = max_missing_frames
        self.stabilize_frames = stabilize_frames
        self.confirm_frames = confirm_frames
        self.confirm_confidence = confirm_confidence

        self._next_id: int = 1
        self.tracks: dict[int, TrackedNote] = {}
        # Session state: counted denominations and history
        self.confirmed_counts: Counter = Counter()
        self.review_queue: list[dict] = []
        self.rejected_items: list[dict] = []

    @property
    def total_amount(self) -> int:
        return sum(int(denom) * count for denom, count in self.confirmed_counts.items() if denom.isdigit())

    def update(self, detections: list[Detection]) -> list[dict]:
        """Update tracker with detections from the current video frame.
        Returns serialized detection items with tracking IDs, states, and canvas coordinates.
        """
        matched_track_ids = set()
        matched_det_indices = set()

        # Match existing tracks with current detections based on IoU and centroid proximity
        for track_id, track in self.tracks.items():
            best_match_idx = None
            best_score = 0.0

            for idx, det in enumerate(detections):
                if idx in matched_det_indices:
                    continue

                sim_iou = iou(track.bbox, det.bbox)
                # Centroid distance score
                tc_x, tc_y = track.centroid
                dc_x = (det.bbox[0] + det.bbox[2]) / 2.0
                dc_y = (det.bbox[1] + det.bbox[3]) / 2.0
                dist = math.hypot(tc_x - dc_x, tc_y - dc_y)

                # Combined proximity score
                score = sim_iou + (0.5 if dist < 80 else (0.2 if dist < 150 else 0.0))

                if (sim_iou > self.iou_threshold or dist < 60) and score > best_score:
                    best_score = score
                    best_match_idx = idx

            if best_match_idx is not None:
                det = detections[best_match_idx]
                matched_track_ids.add(track_id)
                matched_det_indices.add(best_match_idx)

                # Update track properties
                track.bbox = det.bbox
                track.confidence = round((track.confidence * 0.4) + (det.conf * 0.6), 3)
                track.label_history.append(det.label)
                track.conf_history.append(det.conf)
                track.frames_seen += 1
                track.frames_missing = 0

                # Compute majority label
                most_common_label = Counter(track.label_history[-5:]).most_common(1)[0][0]
                track.label = most_common_label

                # Evaluate state transition
                self._evaluate_state(track)
            else:
                track.frames_missing += 1

        # Create new tracks for unmatched detections
        for idx, det in enumerate(detections):
            if idx not in matched_det_indices:
                new_track = TrackedNote(
                    tracking_id=self._next_id,
                    bbox=det.bbox,
                    label=det.label,
                    confidence=det.conf,
                    label_history=[det.label],
                    conf_history=[det.conf],
                )
                self._evaluate_state(new_track)
                self.tracks[self._next_id] = new_track
                self._next_id += 1

        # Remove dead tracks that have been missing too long
        dead_ids = [tid for tid, t in self.tracks.items() if t.frames_missing > self.max_missing_frames]
        for tid in dead_ids:
            del self.tracks[tid]

        # Prepare active tracking output for client
        out = []
        for tid, track in self.tracks.items():
            if track.frames_missing == 0:  # currently visible in this frame
                out.append({
                    "tracking_id": tid,
                    "label": track.label,
                    "confidence": round(track.confidence, 3),
                    "state": track.state,
                    "bbox": [round(v, 1) for v in track.bbox],
                    "counted": track.counted,
                })

        return out

    def _evaluate_state(self, track: TrackedNote):
        """State machine for tracked banknote."""
        if track.label == "non_currency":
            track.state = "REJECT"
            return

        # Check if confidence is in grey zone (< floor or low)
        if track.confidence < 0.45:
            track.state = "REJECT"
            return

        if 0.45 <= track.confidence < self.confirm_confidence:
            track.state = "REVIEW"
            return

        # Check multi-frame stability
        if track.frames_seen < self.stabilize_frames:
            track.state = "DETECTING"
        elif self.stabilize_frames <= track.frames_seen < self.confirm_frames:
            track.state = "STABILIZING"
        else:
            track.state = "CONFIRMED"
            # Add to donation tally exactly once
            if not track.counted and track.label.isdigit():
                track.counted = True
                self.confirmed_counts[track.label] += 1

    def snapshot(self) -> dict:
        """Returns the full session snapshot."""
        return {
            "total_amount": self.total_amount,
            "counts": dict(self.confirmed_counts),
            "active_tracks": len([t for t in self.tracks.values() if t.frames_missing == 0]),
            "confirmed_notes_count": sum(self.confirmed_counts.values()),
        }

    def reset(self):
        """Reset the tracker for a new donation session."""
        self._next_id = 1
        self.tracks.clear()
        self.confirmed_counts.clear()
        self.review_queue.clear()
        self.rejected_items.clear()
