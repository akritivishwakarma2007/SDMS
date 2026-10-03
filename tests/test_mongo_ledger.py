"""Unit tests for MongoLedger:
- Cryptographic hash chaining (SHA-256)
- Ed25519 digital signatures
- Append-only behavior
- Tamper detection (modified payload or deleted block)
- Idempotency & replay protection
- Receipt generation and verification
- External anchor export
"""
from __future__ import annotations
import uuid
import pytest

from sdms.core.ledger import MongoLedger, LedgerError, signing
from sdms.core.ledger.hashing import sha256_hex
from sdms.core.policy import PolicyConfig, ratio, iou


@pytest.fixture
def ledger(tmp_path):
    key_path = str(tmp_path / "server.key")
    # Uses mongomock via mongomock:// URI
    return MongoLedger(mongo_uri="mongomock://localhost", server_key_path=key_path)


def test_append_only_ingest_and_hash_chain(ledger: MongoLedger):
    # Ingest 3 events
    e1, created1 = ledger.ingest({
        "event_id": "evt-01",
        "box_id": "box-test",
        "session_id": "s1",
        "denomination": "500",
        "confidence": 0.96,
        "status": "accepted",
        "items": [{"label": "500", "conf": 0.96, "decision": "ACCEPT"}],
        "frame_sha": sha256_hex(b"frame-01"),
    })
    assert created1 is True
    assert e1["seq"] == 1
    assert e1["prev_hash"] == "0" * 64
    assert e1["record_hash"]

    e2, created2 = ledger.ingest({
        "event_id": "evt-02",
        "box_id": "box-test",
        "session_id": "s1",
        "denomination": "100",
        "confidence": 0.92,
        "status": "accepted",
        "items": [{"label": "100", "conf": 0.92, "decision": "ACCEPT"}],
        "frame_sha": sha256_hex(b"frame-02"),
    })
    assert created2 is True
    assert e2["seq"] == 2
    assert e2["prev_hash"] == e1["record_hash"]

    e3, created3 = ledger.ingest({
        "event_id": "evt-03",
        "box_id": "box-test",
        "session_id": "s1",
        "denomination": "50",
        "confidence": 0.55,
        "status": "review",
        "items": [{"label": "50", "conf": 0.55, "decision": "REVIEW"}],
        "frame_sha": sha256_hex(b"frame-03"),
    })
    assert created3 is True
    assert e3["seq"] == 3
    assert e3["prev_hash"] == e2["record_hash"]

    # Verify complete chain integrity
    res = ledger.verify_chain()
    assert res.ok is True
    assert res.checked == 3
    assert res.first_bad_seq is None


def test_idempotency_and_replay_deduplication(ledger: MongoLedger):
    payload = {
        "event_id": "evt-replay-test",
        "box_id": "box-test",
        "session_id": "s1",
        "denomination": "200",
        "confidence": 0.95,
        "status": "accepted",
        "items": [{"label": "200", "conf": 0.95, "decision": "ACCEPT"}],
        "frame_sha": sha256_hex(b"frame-replay"),
    }
    e1, created1 = ledger.ingest(payload)
    assert created1 is True
    assert e1["seq"] == 1

    # Re-submitting the exact same event_id
    e2, created2 = ledger.ingest(payload)
    assert created2 is False
    assert e2["seq"] == 1
    assert e2["event_id"] == "evt-replay-test"
    assert ledger.events.count_documents({}) == 1


def test_tamper_detection_modified_payload(ledger: MongoLedger):
    # Ingest 2 events
    ledger.ingest({
        "event_id": "evt-t1", "box_id": "box-test", "session_id": "s1",
        "denomination": "100", "status": "accepted", "confidence": 0.95
    })
    ledger.ingest({
        "event_id": "evt-t2", "box_id": "box-test", "session_id": "s1",
        "denomination": "500", "status": "accepted", "confidence": 0.98
    })

    # Tamper with event 1: change items to 2000
    ledger.events.update_one(
        {"seq": 1},
        {"$set": {"denomination": "2000", "items": [{"label": "2000", "conf": 0.99, "decision": "ACCEPT"}]}}
    )

    # Verification must fail and identify corrupted block
    res = ledger.verify_chain()
    assert res.ok is False
    assert res.first_bad_seq == 1
    assert "corrupted" in res.reason.lower() or "mismatch" in res.reason.lower() or "signature" in res.reason.lower()


def test_tamper_detection_deleted_block(ledger: MongoLedger):
    # Ingest 3 events
    for i in range(1, 4):
        ledger.ingest({
            "event_id": f"evt-del-{i}", "box_id": "box-test", "session_id": "s1",
            "denomination": "100", "status": "accepted", "confidence": 0.95
        })
    assert ledger.verify_chain().ok is True

    # Maliciously delete block seq 2
    ledger.events.delete_one({"seq": 2})

    # Verification must fail because sequence continuity or hash continuity is broken
    res = ledger.verify_chain()
    assert res.ok is False
    assert res.first_bad_seq in (2, 3)


def test_receipt_generation_and_verification(ledger: MongoLedger):
    doc, _ = ledger.ingest({
        "event_id": "evt-rcp-01",
        "box_id": "box-test",
        "session_id": "s-live",
        "denomination": "500",
        "confidence": 0.99,
        "status": "accepted"
    })

    receipt = ledger.create_receipt("evt-rcp-01", donor_name="Ramesh Sharma")
    assert receipt["receipt_number"].startswith("RCP-")
    assert receipt["denomination"] == "500"
    assert receipt["donor_name"] == "Ramesh Sharma"
    assert receipt["ledger_hash"] == doc["record_hash"]

    # Verify receipt valid
    v = ledger.verify_receipt(receipt["receipt_id"])
    assert v["ok"] is True
    assert v["chain_status"] == "PASS"

    # Non-existent receipt
    assert ledger.verify_receipt("unknown-id")["ok"] is False


def test_review_queue_resolution_creates_amendment(ledger: MongoLedger):
    # Ingest review item
    orig, _ = ledger.ingest({
        "event_id": "evt-flagged-01",
        "box_id": "box-01",
        "session_id": "s1",
        "denomination": "20",
        "confidence": 0.45,
        "status": "review",
        "items": [{"label": "20", "conf": 0.45, "decision": "REVIEW"}],
        "frame_sha": sha256_hex(b"blur-frame")
    })

    # Auditor resolves as 50
    amend = ledger.resolve_review_item("evt-flagged-01", "50", by_user="auditor-jane", note="Cleaned lens, note is 50")
    assert amend["seq"] == 2
    assert amend["amends"] == "evt-flagged-01"
    assert amend["status"] == "accepted"
    assert amend["denomination"] == "50"

    # Feedback collection recorded audit trail
    fb = ledger.feedback.find_one({"amends": "evt-flagged-01"})
    assert fb is not None
    assert fb["by_user"] == "auditor-jane"
    assert fb["corrected_label"] == "50"

    # Ledger chain must still be cryptographically valid
    res = ledger.verify_chain()
    assert res.ok is True


def test_external_chain_anchor_export(ledger: MongoLedger, tmp_path):
    ledger.ingest({
        "event_id": "evt-anchor-01",
        "box_id": "box-01",
        "session_id": "s1",
        "denomination": "200",
        "confidence": 0.97,
        "status": "accepted"
    })
    anchor_file = str(tmp_path / "anchor.json")
    anchor = ledger.export_chain_head(anchor_file)
    assert anchor["head_seq"] == 1
    assert anchor["head_hash"] != "0" * 64
    assert anchor["events_count"] == 1


def test_policy_ratio_and_iou_bounds():
    policy = PolicyConfig(min_ratio=1.3, max_ratio=3.2, iou_conflict=0.30)
    assert "2000" in policy.valid_denoms

    # Standard banknote bbox [x1, y1, x2, y2]
    # width = 200, height = 100 -> aspect ratio 2.0
    r = ratio([10, 10, 210, 110])
    assert 1.3 <= r <= 3.2

    # Overlapping boxes IoU
    box_a = [0, 0, 100, 100]
    box_b = [50, 0, 150, 100]
    overlap_iou = iou(box_a, box_b)
    # intersection 50x100 = 5000, union = 15000 -> IoU = 0.333 > 0.30
    assert overlap_iou > policy.iou_conflict


def test_mongo_ledger_status_and_reconnect(tmp_path):
    server_key = str(tmp_path / "server.key")
    ledger = MongoLedger(mongo_uri="mongomock://localhost", server_key_path=server_key)

    # Ingest a sample event
    ledger.ingest({
        "event_id": "evt-stat-1",
        "denomination": "500",
        "confidence": 0.99,
        "status": "accepted"
    })

    status = ledger.get_status()
    assert status["connected"] is True
    assert status["is_mock"] is True
    assert status["counts"]["events"] == 1

    # Test reconnecting to another mongomock URI migrates data
    new_status = ledger.reconnect("mongomock://cluster-test/sdms_live")
    assert new_status["connected"] is True
    assert new_status["database"] == "sdms_live"
    assert new_status["counts"]["events"] == 1
    assert ledger.events.find_one({"event_id": "evt-stat-1"}) is not None
