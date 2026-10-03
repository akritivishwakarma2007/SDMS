"""Hash-chained, signed, append-only ledger on SQLite (PostgreSQL later via SQLAlchemy/Alembic).

Tamper-evident, NOT tamper-proof: an attacker with DB access can edit rows, but verify() will flag
the first broken record, and daily anchors held elsewhere catch a full rewrite by someone with the server key.
"""
from __future__ import annotations
import json, sqlite3, threading, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import signing
from .hashing import GENESIS, canonical, record_hash, sha256_hex

STATUSES = {"ACCEPT", "REVIEW", "REJECT", "AMENDMENT"}
SERVER_BOX = "server"

SCHEMA = """
CREATE TABLE IF NOT EXISTS boxes(box_id TEXT PRIMARY KEY, public_key TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY, box_id TEXT NOT NULL, opened_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS events(
  seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, ts TEXT NOT NULL, box_id TEXT NOT NULL,
  session_id TEXT NOT NULL, status TEXT NOT NULL, model_version TEXT NOT NULL, thresholds TEXT NOT NULL,
  items TEXT NOT NULL, frame_sha TEXT NOT NULL, amends TEXT, prev_hash TEXT NOT NULL,
  record_hash TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS event_items(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL,
  seq INTEGER NOT NULL, label TEXT NOT NULL, conf REAL, decision TEXT NOT NULL, reason TEXT, bbox TEXT,
  FOREIGN KEY(event_id) REFERENCES events(event_id));
CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, ts TEXT NOT NULL,
  by_user TEXT NOT NULL, original TEXT NOT NULL, corrected TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS reconciliations(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, ts TEXT NOT NULL,
  by_user TEXT NOT NULL, system_counts TEXT NOT NULL, physical_counts TEXT NOT NULL, variance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_items_no_update BEFORE UPDATE ON event_items BEGIN SELECT RAISE(ABORT,'event_items are append-only'); END;
CREATE TRIGGER IF NOT EXISTS event_items_no_delete BEFORE DELETE ON event_items BEGIN SELECT RAISE(ABORT,'event_items are append-only'); END;
"""

SIGNED_FIELDS = ("event_id", "ts", "box_id", "session_id", "status", "model_version",
                 "thresholds", "items", "frame_sha", "amends")


def signing_bytes(payload: dict) -> bytes:
    return canonical({k: payload.get(k) for k in SIGNED_FIELDS}).encode()


class LedgerError(Exception):
    pass


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    reason: str | None = None

    def as_dict(self):
        return self.__dict__.copy()


class Ledger:
    def __init__(self, db_path: str = ":memory:", server_key_path: str | None = None):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._server_priv = self._load_server_key(server_key_path)

    # ---- keys ----
    def _load_server_key(self, path: str | None) -> str:
        if path and Path(path).exists():
            priv = Path(path).read_text().strip()
            pub = self._conn.execute("SELECT public_key FROM boxes WHERE box_id=?", (SERVER_BOX,)).fetchone()
            if not pub:
                raise LedgerError("server key file exists but server box is not registered in DB")
            return priv
        priv, pub = signing.generate_keypair()
        if path:
            Path(path).write_text(priv)
        self._conn.execute("INSERT OR REPLACE INTO boxes VALUES(?,?,?)", (SERVER_BOX, pub, _now()))
        self._conn.commit()
        return priv

    def register_box(self, box_id: str, public_key: str):
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO boxes VALUES(?,?,?)", (box_id, public_key, _now()))
            self._conn.commit()

    def keys(self) -> dict[str, str]:
        return {r["box_id"]: r["public_key"] for r in self._conn.execute("SELECT * FROM boxes")}

    # ---- ingest ----
    def ingest(self, payload: dict, signature: str) -> tuple[dict, bool]:
        """Returns (event_row, created). Re-sending the same event_id is a no-op (idempotent)."""
        if payload.get("status") not in STATUSES:
            raise LedgerError("bad status")
        for f in ("event_id", "ts", "box_id", "session_id", "model_version", "thresholds", "items", "frame_sha"):
            if payload.get(f) is None:
                raise LedgerError(f"missing field {f}")
        with self._lock:
            keys = self.keys()
            pub = keys.get(payload["box_id"])
            if not pub:
                raise LedgerError("unknown box")
            if not signing.verify(pub, signing_bytes(payload), signature):
                raise LedgerError("bad signature")
            existing = self._conn.execute("SELECT * FROM events WHERE event_id=?", (payload["event_id"],)).fetchone()
            if existing:
                return dict(existing), False
            s = self._conn.execute("SELECT * FROM sessions WHERE session_id=?", (payload["session_id"],)).fetchone()
            if s and s["closed_at"] and payload["status"] != "AMENDMENT":
                raise LedgerError("session closed")
            if not s:
                self._conn.execute("INSERT INTO sessions VALUES(?,?,?,NULL)",
                                   (payload["session_id"], payload["box_id"], _now()))
            last = self._conn.execute("SELECT seq, record_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq, prev = (last["seq"] + 1, last["record_hash"]) if last else (1, GENESIS)
            h = record_hash(prev, seq, payload["ts"], payload["box_id"], payload["items"], payload["frame_sha"],
                            payload["status"], payload["event_id"], payload.get("amends"))
            self._conn.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (seq, payload["event_id"], payload["ts"], payload["box_id"], payload["session_id"], payload["status"],
                 payload["model_version"], canonical(payload["thresholds"]), canonical(payload["items"]),
                 payload["frame_sha"], payload.get("amends"), prev, h, signature))
            for it in payload.get("items", []):
                self._conn.execute(
                    "INSERT INTO event_items(event_id, seq, label, conf, decision, reason, bbox) VALUES(?,?,?,?,?,?,?)",
                    (payload["event_id"], seq, it.get("label", ""), it.get("conf", 0.0), it.get("decision", "ACCEPT"), it.get("reason", ""), json.dumps(it.get("bbox", []))))
            self._conn.commit()
            return dict(self._conn.execute("SELECT * FROM events WHERE seq=?", (seq,)).fetchone()), True

    def amend(self, event_id: str, corrected_items: list[dict], by_user: str, note: str = "") -> dict:
        """Corrections are NEW amendment events (never UPDATE). Signed by the server key."""
        with self._lock:
            orig = self.get_event(event_id)
            if not orig:
                raise LedgerError("no such event")
            if self._conn.execute("SELECT 1 FROM events WHERE amends=?", (event_id,)).fetchone():
                raise LedgerError("already amended")
            payload = {
                "event_id": f"amend-{uuid.uuid4().hex[:16]}", "ts": _now(), "box_id": SERVER_BOX,
                "session_id": orig["session_id"], "status": "AMENDMENT", "model_version": orig["model_version"],
                "thresholds": {"amended_by": by_user}, "items": corrected_items,
                "frame_sha": orig["frame_sha"], "amends": event_id}
            row, _ = self.ingest(payload, signing.sign(self._server_priv, signing_bytes(payload)))
            self._conn.execute("INSERT INTO feedback(event_id,ts,by_user,original,corrected,note) VALUES(?,?,?,?,?,?)",
                               (event_id, _now(), by_user, orig["items"], canonical(corrected_items), note))
            self._conn.commit()
            return row

    # ---- queries ----
    def rows(self) -> list[dict]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM events ORDER BY seq")]

    def get_event(self, event_id: str) -> dict | None:
        r = self._conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        return dict(r) if r else None

    def review_queue(self) -> list[dict]:
        amended = {r["amends"] for r in self._conn.execute("SELECT amends FROM events WHERE amends IS NOT NULL")}
        return [r for r in self.rows() if r["status"] == "REVIEW" and r["event_id"] not in amended]

    def effective_counts(self, session_id: str | None = None) -> dict[str, int]:
        """What is actually counted: ACCEPT items, replaced by amendments where they exist. REVIEW counts nothing."""
        rows = [r for r in self.rows() if session_id is None or r["session_id"] == session_id]
        counted: dict[str, list] = {}
        for r in rows:
            items = json.loads(r["items"])
            if r["status"] == "ACCEPT":
                counted[r["event_id"]] = [i["label"] for i in items if i.get("decision") == "ACCEPT"]
        for r in rows:
            if r["status"] == "AMENDMENT":
                counted[r["amends"]] = [i["label"] for i in json.loads(r["items"])]
        totals: dict[str, int] = {}
        for labels in counted.values():
            for l in labels:
                totals[l] = totals.get(l, 0) + 1
        return totals

    @staticmethod
    def total_value(counts: dict[str, int]) -> int:
        return sum(int(k) * v for k, v in counts.items())

    def close_session(self, session_id: str):
        with self._lock:
            self._conn.execute("UPDATE sessions SET closed_at=? WHERE session_id=? AND closed_at IS NULL", (_now(), session_id))
            self._conn.commit()

    def reconcile(self, session_id: str, physical: dict[str, int], by_user: str) -> dict:
        system = self.effective_counts(session_id)
        denoms = sorted(set(system) | set(physical), key=int)
        variance = {d: {"system": system.get(d, 0), "physical": physical.get(d, 0),
                        "diff": physical.get(d, 0) - system.get(d, 0),
                        "value_diff": (physical.get(d, 0) - system.get(d, 0)) * int(d)} for d in denoms}
        report = {"session_id": session_id, "by_user": by_user,
                  "system_total": self.total_value(system), "physical_total": self.total_value(physical),
                  "variance_total": self.total_value(physical) - self.total_value(system),
                  "pending_review": len([r for r in self.review_queue() if r["session_id"] == session_id]),
                  "per_denomination": variance}
        with self._lock:
            self._conn.execute("INSERT INTO reconciliations(session_id,ts,by_user,system_counts,physical_counts,variance) VALUES(?,?,?,?,?,?)",
                               (session_id, _now(), by_user, canonical(system), canonical(physical), canonical(report)))
            self._conn.commit()
        return report

    # ---- integrity ----
    def verify(self, rows: list[dict] | None = None, keys: dict[str, str] | None = None) -> VerifyResult:
        """Walk the chain; report the FIRST broken record. Checks: sequence, prev link, hash, signature, duplicate ids."""
        rows = self.rows() if rows is None else rows
        keys = self.keys() if keys is None else keys
        prev, seen = GENESIS, set()
        for expected_seq, r in enumerate(rows, start=1):
            bad = lambda why: VerifyResult(False, expected_seq - 1, r.get("seq"), why)
            if r["seq"] != expected_seq:
                return bad("sequence gap or reorder (deleted/reordered rows)")
            if r["event_id"] in seen:
                return bad("duplicate event_id (replayed payload)")
            seen.add(r["event_id"])
            if r["prev_hash"] != prev:
                return bad("prev_hash does not match previous record")
            items = json.loads(r["items"])
            h = record_hash(prev, r["seq"], r["ts"], r["box_id"], items, r["frame_sha"], r["status"], r["event_id"], r["amends"])
            if h != r["record_hash"]:
                return bad("record hash mismatch (row contents edited)")
            payload = {**r, "items": items, "thresholds": json.loads(r["thresholds"])}
            pub = keys.get(r["box_id"])
            if not pub or not signing.verify(pub, signing_bytes(payload), r["signature"]):
                return bad("invalid signature")
            prev = r["record_hash"]
        return VerifyResult(True, len(rows))

    def anchor(self) -> dict:
        """Chain head. Export this to a DIFFERENT place daily (email, object store, printout)."""
        rows = self.rows()
        if not rows:
            return {"seq": 0, "record_hash": GENESIS, "ts": _now()}
        return {"seq": rows[-1]["seq"], "record_hash": rows[-1]["record_hash"], "ts": _now()}

    def check_anchor(self, anchor: dict) -> VerifyResult:
        """Catches truncation and full rewrites: the record at anchor.seq must still have the anchored hash."""
        res = self.verify()
        if not res.ok:
            return res
        if anchor["seq"] == 0:
            return res
        row = self._conn.execute("SELECT record_hash FROM events WHERE seq=?", (anchor["seq"],)).fetchone()
        if not row or row["record_hash"] != anchor["record_hash"]:
            return VerifyResult(False, res.checked, anchor["seq"], "chain no longer matches external anchor (truncated/rewritten)")
        return res

    def export_anchor(self, out_dir: str | Path = "data/anchors") -> Path:
        p = Path(out_dir)
        p.mkdir(parents=True, exist_ok=True)
        anc = self.anchor()
        fname = p / f"anchor_seq_{anc['seq']:06d}.json"
        fname.write_text(json.dumps(anc, indent=2))
        return fname


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
