"""WebSocket handler for real-time live camera banknote recognition.
Streams video frames from browser -> detector -> NoteTracker -> client with canvas overlays.
"""
from __future__ import annotations
import base64
import json
import time
from fastapi import WebSocket, WebSocketDisconnect

from sdms.core.sources.interfaces import Frame
from sdms.core.vision.detector import ColorFeatureDetector, Detector, NeuralCurrencyDetector
from sdms.core.vision.tracker import NoteTracker


class LiveDetectionManager:
    def __init__(self, detector: Detector | None = None):
        self.detector = detector or NeuralCurrencyDetector()

    async def handle_websocket(self, websocket: WebSocket):
        await websocket.accept()
        tracker = NoteTracker()
        frame_idx = 0

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                action = msg.get("action", "frame")

                if action == "reset":
                    tracker.reset()
                    await websocket.send_json({
                        "type": "reset_ack",
                        "session": tracker.snapshot(),
                    })
                    continue

                if action == "frame":
                    img_data = msg.get("image", "")
                    if not img_data:
                        continue

                    # Strip data URI header if present
                    if "," in img_data:
                        img_data = img_data.split(",", 1)[1]

                    try:
                        raw_bytes = base64.b64decode(img_data)
                    except Exception:
                        continue

                    frame_idx += 1
                    t0 = time.perf_counter()
                    frame = Frame(raw_bytes, trigger_id=f"live-cam-{frame_idx:06d}")
                    detections = self.detector.detect(frame)
                    tracked_items = tracker.update(detections)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

                    # Check if any note currently needs review
                    has_review = any(it["state"] == "REVIEW" for it in tracked_items)

                    await websocket.send_json({
                        "type": "detection",
                        "frame_id": frame_idx,
                        "latency_ms": elapsed_ms,
                        "items": tracked_items,
                        "session": tracker.snapshot(),
                        "review_alert": has_review,
                    })

        except WebSocketDisconnect:
            pass
