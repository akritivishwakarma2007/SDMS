"""R4 (four tamper attacks), R5 (idempotency), amendments, anchoring."""
import copy, json
from tests.helpers import send, fill


def test_clean_chain_verifies(ledger, box):
    fill(ledger, box)
    r = ledger.verify()
    assert r.ok and r.checked == 6


def test_review_and_reject_are_chained_too(ledger, box):
    send(ledger, box, ["100"], "a", "blur")
    send(ledger, box, ["non_currency"], "b")
    assert {r["status"] for r in ledger.rows()} <= {"REVIEW", "REJECT", "ACCEPT"} and ledger.verify().ok


def test_idempotent_retry(ledger, box):
    payload, sig, (_, created) = send(ledger, box, ["50"], "x")
    assert created
    before = ledger.rows()
    for _ in range(3):
        _, again = ledger.ingest(payload, sig)
        assert again is False
    assert ledger.rows() == before


def test_append_only_triggers_block_update_and_delete(ledger, box):
    fill(ledger, box, 2)
    for sql in ("UPDATE events SET status='ACCEPT' WHERE seq=1", "DELETE FROM events WHERE seq=1"):
        try:
            ledger._conn.execute(sql); assert False, "should be blocked"
        except Exception as e:
            assert "append-only" in str(e)


def _bypass(ledger):   # an attacker with DB admin rights removes the triggers
    ledger._conn.execute("DROP TRIGGER events_no_update"); ledger._conn.execute("DROP TRIGGER events_no_delete")


def test_attack_byte_edit(ledger, box):
    fill(ledger, box); _bypass(ledger)
    it = json.loads(ledger.rows()[2]["items"]); it[0]["label"] = "500"
    ledger._conn.execute("UPDATE events SET items=? WHERE seq=3", (json.dumps(it, sort_keys=True, separators=(",", ":")),))
    r = ledger.verify()
    assert not r.ok and r.first_bad_seq == 3 and "hash" in r.reason


def test_attack_deleted_row(ledger, box):
    fill(ledger, box); _bypass(ledger)
    ledger._conn.execute("DELETE FROM events WHERE seq=3")
    r = ledger.verify()
    assert not r.ok and r.first_bad_seq == 4


def test_attack_reordered_rows(ledger, box):
    fill(ledger, box)
    rows = ledger.rows(); rows[2], rows[3] = rows[3], rows[2]
    r = ledger.verify(rows=rows)
    assert not r.ok and r.first_bad_seq == 4


def test_attack_replayed_payload_rows(ledger, box):
    fill(ledger, box)
    rows = ledger.rows()
    dup = copy.deepcopy(rows[1]); dup["seq"] = 7
    r = ledger.verify(rows=rows + [dup])
    assert not r.ok and "duplicate" in r.reason


def test_rehashed_forgery_fails_signature(ledger, box):
    """Attacker edits a row AND recomputes the whole chain, but has no box key."""
    from sdms.core.ledger.hashing import record_hash
    fill(ledger, box, 3); _bypass(ledger)
    rows = ledger.rows(); prev = rows[0]["prev_hash"]
    for r in rows:
        items = json.loads(r["items"])
        if r["seq"] == 2: items[0]["label"] = "500"
        r["items"] = json.dumps(items, sort_keys=True, separators=(",", ":"))
        r["prev_hash"] = prev
        r["record_hash"] = record_hash(prev, r["seq"], r["ts"], r["box_id"], items, r["frame_sha"], r["status"], r["event_id"], r["amends"])
        prev = r["record_hash"]
    res = ledger.verify(rows=rows)
    assert not res.ok and res.first_bad_seq == 2 and "signature" in res.reason


def test_anchor_detects_truncation(ledger, box):
    fill(ledger, box); anchor = ledger.anchor(); _bypass(ledger)
    ledger._conn.execute("DELETE FROM events WHERE seq>4")
    assert ledger.verify().ok                   # a truncated chain is internally consistent...
    assert not ledger.check_anchor(anchor).ok   # ...but the external anchor catches it


def test_unknown_box_and_bad_signature_rejected(ledger, box):
    import pytest
    from sdms.core.ledger import LedgerError
    payload, sig, _ = send(ledger, box, ["10"], "z")
    p2 = {**payload, "event_id": "new", "box_id": "ghost"}
    with pytest.raises(LedgerError): ledger.ingest(p2, sig)
    p3 = {**payload, "event_id": "new2"}
    with pytest.raises(LedgerError): ledger.ingest(p3, sig)   # signature no longer matches


def test_amendment_resolves_review_and_counts(ledger, box):
    payload, _, _ = send(ledger, box, ["100"], "r1", "blur")
    assert payload["status"] == "REVIEW" and ledger.effective_counts() == {}
    assert len(ledger.review_queue()) == 1
    ledger.amend(payload["event_id"], [{"label": "100", "decision": "ACCEPT"}], "aud")
    assert ledger.review_queue() == [] and ledger.effective_counts() == {"100": 1}
    assert ledger.verify().ok
    assert ledger._conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"] == 1


def test_reconcile_variance(ledger, box):
    for i, d in enumerate(["100", "100", "500"]): send(ledger, box, [d], f"q{i}")
    rep = ledger.reconcile("s1", {"100": 2, "500": 1, "50": 1}, "aud")
    assert rep["system_total"] == 700 and rep["variance_total"] == 50
    assert rep["per_denomination"]["50"]["diff"] == 1


def test_closed_session_rejects_new_events(ledger, box):
    import pytest
    from sdms.core.ledger import LedgerError
    send(ledger, box, ["10"], "c1"); ledger.close_session("s1")
    with pytest.raises(LedgerError): send(ledger, box, ["10"], "c2")
