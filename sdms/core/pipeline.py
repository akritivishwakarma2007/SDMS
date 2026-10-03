"""Box-side pipeline: Frame -> detect -> policy -> signed event payload."""
from __future__ import annotations
from sdms.core.ledger import signing, signing_bytes
from sdms.core.ledger.hashing import sha256_hex
from sdms.core.policy import PolicyConfig, decide_frame
from sdms.core.sources.interfaces import Clock, Frame


class BoxPipeline:
    def __init__(self, box_id: str, private_key: str, detector, policy: PolicyConfig, clock: Clock, session_id: str):
        self.box_id, self.priv, self.detector, self.policy, self.clock, self.session_id = \
            box_id, private_key, detector, policy, clock, session_id

    def process(self, frame: Frame) -> tuple[dict, str]:
        """Returns (payload, signature). event_id derives from box+trigger, so retries are idempotent."""
        dets = self.detector.detect(frame)
        status, items = decide_frame(dets, self.policy)
        payload = {
            "event_id": sha256_hex(f"{self.box_id}:{frame.trigger_id}")[:32],
            "ts": self.clock.now().isoformat(), "box_id": self.box_id, "session_id": self.session_id,
            "status": status, "model_version": self.detector.model_version,
            "thresholds": {"floor": self.policy.floor, "accept": self.policy.accept_thresholds},
            "items": items, "frame_sha": sha256_hex(frame.data), "amends": None}
        return payload, signing.sign(self.priv, signing_bytes(payload))
