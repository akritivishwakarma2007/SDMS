import base64
import os
import pytest
from fastapi.testclient import TestClient
from sdms.api.main import create_app
from sdms.core.ledger import Ledger, generate_keypair
from sdms.core.ledger.hashing import sha256_hex
from sdms.core.pipeline import BoxPipeline
from sdms.core.policy import PolicyConfig
from sdms.core.sources.interfaces import Frame, SimClock
from sdms.core.vision.detector import MockDetector


@pytest.fixture
def env(tmp_path):
    app = create_app(Ledger(":memory:"), tmp_path / "frames")
    c = TestClient(app)
    tok = lambda u, p: {"Authorization": "Bearer " + c.post("/auth/login", json={"username": u, "password": p}).json()["access_token"]}
    admin_pw = os.environ.get("SDMS_ADMIN_PASSWORD", "admin")
    admin = tok("admin", admin_pw)
    c.post("/users", json={"username": "aud", "password": "pw", "role": "auditor"}, headers=admin)
    priv, pub = generate_keypair()
    c.post("/boxes", json={"box_id": "box-1", "public_key": pub}, headers=admin)
    box = BoxPipeline("box-1", priv, MockDetector(seed=2, confusion_rate=0), PolicyConfig(), SimClock(), "s1")
    return c, admin, tok("aud", "pw"), box


def drop(c, box, truth, tid, quality="ok"):
    data = f"frame-{tid}".encode()
    p, s = box.process(Frame(data, tid, {"truth": truth, "quality": quality}))
    return c.post("/ingest/event", json={"payload": p, "signature": s, "frame_b64": base64.b64encode(data).decode()}), p


def test_ingest_idempotent_and_public_view(env):
    c, admin, aud, box = env
    r, p = drop(c, box, ["500"], "a"); assert r.json()["created"] is True
    r2 = c.post("/ingest/event", json={"payload": p, "signature": box.process(Frame(b"frame-a", "a", {"truth": ["500"]}))[1]})
    assert c.get("/analytics/realtime").json()["total_value"] == 500      # public, no token needed
    assert len(c.get("/events", headers=aud).json()) == 1


def test_role_separation_R6(env):
    c, admin, aud, box = env
    r, p = drop(c, box, ["500"], "a")
    assert c.get("/events").status_code == 401                            # public: no raw data
    assert c.get(f"/frames/{p['frame_sha']}").status_code == 401
    assert c.get(f"/frames/{p['frame_sha']}", headers=aud).status_code == 200
    aud_tok = aud["Authorization"].split(" ")[1]
    assert c.get(f"/frames/{p['frame_sha']}?token={aud_tok}").status_code == 200
    assert c.get(f"/frames/{p['frame_sha']}?token=bad_token").status_code == 401
    assert c.post("/users", json={"username": "x", "password": "y", "role": "admin"}, headers=aud).status_code == 403
    assert c.post("/boxes", json={"box_id": "z", "public_key": "k"}, headers=aud).status_code == 403


def test_review_flow_and_reconcile(env):
    c, admin, aud, box = env
    _, p = drop(c, box, ["100"], "blurry", "blur")
    q = c.get("/review/queue", headers=aud).json(); assert len(q) == 1
    assert c.post(f"/review/{p['event_id']}/resolve", json={"labels": ["100"]}, headers=aud).status_code == 200
    assert c.get("/review/queue", headers=aud).json() == []
    rep = c.post("/sessions/s1/reconcile", json={"physical": {"100": 1}}, headers=aud).json()
    assert rep["variance_total"] == 0 and c.get("/ledger/verify", headers=aud).json()["ok"]


def test_ingest_rejects_forged_amendment_and_bad_frame(env):
    c, admin, aud, box = env
    r, p = drop(c, box, ["10"], "a")
    p2 = {**p, "status": "AMENDMENT"}
    assert c.post("/ingest/event", json={"payload": p2, "signature": "x"}).status_code == 403
    data = b"other"; p3, s3 = box.process(Frame(b"real", "b", {"truth": ["10"]}))
    assert c.post("/ingest/event", json={"payload": p3, "signature": s3, "frame_b64": base64.b64encode(data).decode()}).status_code == 400


def test_export_csv_and_txt(env):
    c, admin, aud, box = env
    drop(c, box, ["500"], "x1")
    res_csv = c.get("/sessions/s1/export?format=csv", headers=aud)
    assert res_csv.status_code == 200
    assert "500" in res_csv.text and "Session ID" in res_csv.text
    res_txt = c.get("/sessions/s1/export?format=txt", headers=aud)
    assert res_txt.status_code == 200 and "Reconciliation Report" in res_txt.text


def test_donation_confirmation_and_receipt(env):
    c, admin, aud, box = env
    res = c.post("/donations/confirm", json={
        "session_id": "live-test-1",
        "counts": {"500": 1, "200": 2, "100": 1},
        "donor_name": "Test Donor"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1000
    assert "SDMS-2026-" in data["donation_id"]
    assert data["record_hash"]

    # Verify receipt retrieval
    rec_res = c.get(f"/donations/{data['donation_id']}/receipt")
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["total"] == 1000
    assert rec_data["counts"]["500"] == 1
    assert rec_data["counts"]["200"] == 2


def test_admin_analytics(env):
    c, admin, aud, box = env
    # Anonymous cannot access
    assert c.get("/admin/analytics").status_code == 401
    # Auditor cannot access admin analytics
    assert c.get("/admin/analytics", headers=aud).status_code == 403
    # Admin can access
    res = c.get("/admin/analytics", headers=admin)
    assert res.status_code == 200
    data = res.json()
    assert "total_amount" in data
    assert "accuracy_rate" in data
    assert "notes_distribution" in data


def test_samples_and_vision_classify(env):
    c, admin, aud, box = env
    # Check sample list
    res_list = c.get("/samples/currency")
    assert res_list.status_code == 200
    samples = res_list.json()["samples"]
    assert "500" in samples
    assert "100" in samples

    # Check sample note fetching
    res_sample = c.get("/samples/currency/500")
    assert res_sample.status_code == 200
    sample_data = res_sample.json()
    assert sample_data["denomination"] == "500"
    assert "data_url" in sample_data
    assert sample_data["data_url"].startswith("data:image/jpeg;base64,")

    # Test /vision/classify with sample
    classify_res = c.post("/vision/classify", json={"image_b64": sample_data["data_url"]})
    assert classify_res.status_code == 200
    c_data = classify_res.json()
    assert "label" in c_data
    assert "conf" in c_data
    assert "status" in c_data
    assert "probabilities" in c_data
    assert "seq" in c_data
    assert "event_id" in c_data


def test_system_db_endpoints(env):
    c, admin, aud, box = env
    res = c.get("/system/db-status")
    assert res.status_code == 200
    data = res.json()
    assert "connected" in data
    assert "is_mock" in data
    assert "counts" in data
    assert "events" in data["counts"]

    # Test connect endpoint with mongomock
    conn_res = c.post("/system/db-connect", json={"uri": "mongomock://test-cluster/sdms_reconnected", "persist_to_env": False})
    assert conn_res.status_code == 200
    conn_data = conn_res.json()
    assert conn_data["ok"] is True
    assert conn_data["status"]["database"] == "sdms_reconnected"



