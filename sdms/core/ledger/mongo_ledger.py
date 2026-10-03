"""Tamper-evident, append-only MongoDB ledger for SDMS.

Enforces cryptographic hash chaining and Ed25519 signatures across all events.
Collections:
  - boxes: Registered donation box devices and their Ed25519 public keys.
  - sessions: Active and closed cashier counting sessions.
  - events: The immutable, append-only ledger of banknote drops and amendments.
  - event_items: Individual candidate contours and detections within an event.
  - receipts: Cryptographically sealed donation receipts tied to ledger event hashes.
  - feedback: Human auditor override and relabeling audit trail.
  - users: Authorized staff credentials (Operator, Auditor, Admin).
  - reconciliations: Session closing cash counts, variances, and anti-pilferage audits.
"""
from __future__ import annotations
import base64
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import signing
from .hashing import GENESIS, canonical, sha256_hex

def load_env_file():
    """Load environment variables from project .env if present."""
    root_cands = [Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"]
    try:
        from dotenv import load_dotenv
        for cand in root_cands:
            if cand.exists():
                load_dotenv(cand, override=False)
                break
    except Exception:
        pass

    for cand in root_cands:
        if cand.exists():
            try:
                for line in cand.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
                break
            except Exception:
                pass

load_env_file()


def mask_uri(uri: str) -> str:
    """Mask credentials in MongoDB URI for safe display."""
    if "@" in uri:
        prefix, rest = uri.split("@", 1)
        scheme_user = prefix.split("://", 1)
        if len(scheme_user) == 2 and ":" in scheme_user[1]:
            scheme, creds = scheme_user
            user, _ = creds.split(":", 1)
            return f"{scheme}://{user}:****@{rest}"
    return uri


SERVER_BOX = "server"
DEFAULT_MONGO_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/sdms")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LedgerError(Exception):
    pass


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    first_bad_seq: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# Canonical JSON Schema validator definition for events
EVENTS_JSON_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "seq", "event_id", "box_id", "session_id", "timestamp",
            "status", "denomination", "confidence", "model_version",
            "frame_sha256", "prev_hash", "record_hash", "signature"
        ],
        "properties": {
            "seq": {"bsonType": "int", "minimum": 1, "description": "Strictly ascending sequence number"},
            "event_id": {"bsonType": "string", "description": "Unique event identifier"},
            "box_id": {"bsonType": "string"},
            "session_id": {"bsonType": "string"},
            "timestamp": {"bsonType": "string"},
            "status": {"enum": ["accepted", "review", "rejected", "amendment", "ACCEPT", "REVIEW", "REJECT", "AMENDMENT"]},
            "denomination": {"bsonType": "string"},
            "confidence": {"bsonType": ["double", "int"]},
            "model_version": {"bsonType": "string"},
            "frame_sha256": {"bsonType": "string"},
            "prev_hash": {"bsonType": "string"},
            "record_hash": {"bsonType": "string"},
            "signature": {"bsonType": "string"},
            "amends": {"bsonType": ["string", "null"]}
        }
    }
}


SIGNED_FIELDS = (
    "event_id", "ts", "box_id", "session_id", "status", "model_version",
    "thresholds", "items", "frame_sha", "amends"
)


def signing_bytes(payload: dict) -> bytes:
    """Canonical signing bytes matching the spec for Ed25519 digital signature."""
    clean = {}
    for k in SIGNED_FIELDS:
        if k == "ts":
            clean["ts"] = payload.get("ts") or payload.get("timestamp") or ""
        elif k == "frame_sha":
            clean["frame_sha"] = payload.get("frame_sha") or payload.get("frame_sha256") or ""
        else:
            clean[k] = payload.get(k)
    return canonical(clean).encode("utf-8")


def compute_record_hash(prev_hash: str, sign_data: bytes) -> str:
    """record_hash = sha256(prev_hash + canonical_json(payload))."""
    return sha256_hex(prev_hash.encode("utf-8") + sign_data)


class MongoLedger:
    """MongoDB Append-Only Ledger for SDMS with automatic mongomock fallback."""

    def __init__(self, mongo_uri: str | None = None, db_name: str | None = None, server_key_path: str | None = None):
        self.uri = mongo_uri or os.environ.get("MONGODB_URI", DEFAULT_MONGO_URI)
        self.db_name = db_name or os.environ.get("MONGODB_DB", "sdms")
        self._lock = threading.RLock()
        self.is_mock = False

        # Attempt connection to real MongoDB; fallback to mongomock if unavailable
        self.client, self.db = self._init_client(self.uri, self.db_name)

        # Reference collections
        self.boxes = self.db["boxes"]
        self.sessions = self.db["sessions"]
        self.events = self.db["events"]
        self.event_items = self.db["event_items"]
        self.receipts = self.db["receipts"]
        self.feedback = self.db["feedback"]
        self.users = self.db["users"]
        self.reconciliations = self.db["reconciliations"]

        self._init_indexes()
        self._server_priv = self._load_server_key(server_key_path)

    def _init_client(self, uri: str, db_name: str):
        if uri.startswith("mongomock://"):
            import mongomock
            client = mongomock.MongoClient()
            self.is_mock = True
            return client, client[db_name]

        try:
            from pymongo import MongoClient
            client_kwargs: dict[str, Any] = {"serverSelectionTimeoutMS": 2000}
            if uri.startswith("mongodb+srv://") or "ssl=true" in uri.lower() or "tls=true" in uri.lower():
                try:
                    import certifi
                    client_kwargs["tlsCAFile"] = certifi.where()
                except Exception:
                    pass
            client = MongoClient(uri, **client_kwargs)
            client.admin.command("ping")
            self.is_mock = False
            return client, client[db_name]
        except Exception:
            # Fallback to mongomock for test and offline developer environments
            import mongomock
            client = mongomock.MongoClient()
            self.is_mock = True
            return client, client[db_name]

    def _init_indexes(self):
        try:
            self.boxes.create_index("box_id", unique=True)
            self.sessions.create_index("session_id", unique=True)
            self.events.create_index("seq", unique=True)
            self.events.create_index("event_id", unique=True)
            self.events.create_index("timestamp")
            self.event_items.create_index("event_id")
            self.event_items.create_index("seq")
            self.receipts.create_index("receipt_id", unique=True)
            self.receipts.create_index("session_id")
            self.feedback.create_index("event_id")
            self.users.create_index("username", unique=True)
            self.reconciliations.create_index("session_id")
        except Exception:
            pass

    def get_status(self) -> dict[str, Any]:
        """Return live MongoDB connection status, latency, and collection tallies."""
        connected = True
        latency_ms = 1
        if not self.is_mock:
            try:
                t0 = datetime.now()
                self.client.admin.command("ping")
                latency_ms = max(1, int((datetime.now() - t0).total_seconds() * 1000))
            except Exception:
                connected = False

        counts = {}
        for col_name in ["events", "event_items", "receipts", "sessions", "boxes", "users", "reconciliations", "feedback"]:
            try:
                counts[col_name] = self.db[col_name].count_documents({})
            except Exception:
                counts[col_name] = 0

        return {
            "connected": connected,
            "is_mock": self.is_mock,
            "uri": self.uri,
            "uri_masked": mask_uri(self.uri),
            "database": self.db_name,
            "latency_ms": latency_ms,
            "counts": counts,
        }

    def reconnect(self, new_uri: str, db_name: str | None = None) -> dict[str, Any]:
        """Hot-reconnect ledger to a real MongoDB instance (e.g. MongoDB Atlas or local)."""
        target_db = db_name
        if not target_db or target_db == "sdms":
            try:
                path_part = new_uri.split("://", 1)[-1].split("?", 1)[0]
                if "/" in path_part:
                    cand = path_part.split("/")[-1].strip()
                    if cand:
                        target_db = cand
            except Exception:
                pass
        target_db = target_db or self.db_name

        if new_uri.startswith("mongomock://"):
            import mongomock
            client = mongomock.MongoClient()
            is_mock = True
        else:
            from pymongo import MongoClient
            client = MongoClient(new_uri, serverSelectionTimeoutMS=4000)
            # Test ping; raises Exception if unable to connect
            client.admin.command("ping")
            is_mock = False

        with self._lock:
            old_db = self.db
            self.uri = new_uri
            self.db_name = target_db
            self.client = client
            self.db = client[target_db]
            self.is_mock = is_mock

            # Update collection references
            self.boxes = self.db["boxes"]
            self.sessions = self.db["sessions"]
            self.events = self.db["events"]
            self.event_items = self.db["event_items"]
            self.receipts = self.db["receipts"]
            self.feedback = self.db["feedback"]
            self.users = self.db["users"]
            self.reconciliations = self.db["reconciliations"]

            self._init_indexes()

            # Ensure server key box entry in new db
            if hasattr(self, "_server_priv"):
                pub = signing.public_from_private(self._server_priv)
                self.boxes.update_one(
                    {"box_id": SERVER_BOX},
                    {"$set": {"box_id": SERVER_BOX, "public_key": pub, "created_at": _now(), "location": "Ledger Server HSM"}},
                    upsert=True
                )

            # If migrating from mock or old DB, copy non-empty collections to the new DB
            if old_db is not None:
                for col_name in ["users", "boxes", "sessions", "events", "event_items", "receipts", "feedback", "reconciliations"]:
                    try:
                        old_docs = list(old_db[col_name].find({}))
                        for d in old_docs:
                            key_field = "event_id" if "event_id" in d else ("session_id" if "session_id" in d else ("username" if "username" in d else "_id"))
                            if key_field in d:
                                filter_q = {key_field: d[key_field]}
                                copy_d = dict(d)
                                copy_d.pop("_id", None)
                                self.db[col_name].update_one(filter_q, {"$set": copy_d}, upsert=True)
                    except Exception:
                        pass

        return self.get_status()

    def _load_server_key(self, path: str | None) -> str:
        with self._lock:
            if path and Path(path).exists():
                priv = Path(path).read_text().strip()
                pub = signing.public_from_private(priv)
            else:
                priv, pub = signing.generate_keypair()
                if path:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(priv)

            self.boxes.update_one(
                {"box_id": SERVER_BOX},
                {"$set": {"box_id": SERVER_BOX, "public_key": pub, "created_at": _now(), "location": "Ledger Server HSM"}},
                upsert=True
            )
            return priv

    def register_box(self, box_id: str, public_key: str, location: str = "Donation Sanctum"):
        with self._lock:
            self.boxes.update_one(
                {"box_id": box_id},
                {"$set": {"box_id": box_id, "public_key": public_key, "location": location, "status": "online", "last_heartbeat": _now()}},
                upsert=True
            )

    def keys(self) -> dict[str, str]:
        return {r["box_id"]: r["public_key"] for r in self.boxes.find({}, {"_id": 0})}

    # =========================================================
    # Append-Only Ledger Ingestion
    # =========================================================
    def ingest(self, payload: dict, signature: str | None = None) -> tuple[dict, bool]:
        """Ingests an event into the append-only ledger.
        
        Assigns the next strictly increasing seq, computes hash chaining,
        attaches Ed25519 digital signature, and writes to MongoDB.
        Re-submitting the same event_id is idempotently deduplicated.
        """
        event_id = payload.get("event_id") or f"evt-{uuid.uuid4().hex[:16]}"
        with self._lock:
            # 1. Idempotency Check
            existing = self.events.find_one({"event_id": event_id})
            if existing:
                existing["_id"] = str(existing["_id"])
                return existing, False

            # 2. Determine previous block and next seq
            last_event = self.events.find_one(sort=[("seq", -1)])
            if last_event:
                seq = int(last_event["seq"]) + 1
                prev_hash = str(last_event["record_hash"])
            else:
                seq = 1
                prev_hash = GENESIS

            # 3. Canonicalize payload fields
            ts = payload.get("ts") or payload.get("timestamp") or _now()
            box_id = payload.get("box_id") or SERVER_BOX
            session_id = payload.get("session_id") or "session-live"
            status = str(payload.get("status") or "accepted")

            # Handle primary denomination and confidence
            items = payload.get("items") or []
            if items:
                denom = str(items[0].get("label", "non_currency"))
                conf = float(items[0].get("conf", 0.95))
            else:
                denom = str(payload.get("denomination", "non_currency"))
                conf = float(payload.get("confidence", 0.95))

            model_version = payload.get("model_version") or "mobilenetv2-keras-v1"
            frame_sha = payload.get("frame_sha") or payload.get("frame_sha256") or sha256_hex(b"synthetic-frame")
            amends = payload.get("amends") or None

            doc_payload = {
                "box_id": box_id,
                "session_id": session_id,
                "ts": ts,
                "status": status,
                "denomination": denom,
                "confidence": round(conf, 4),
                "model_version": model_version,
                "frame_sha": frame_sha,
                "event_id": event_id,
                "thresholds": payload.get("thresholds", {}),
                "items": items,
                "amends": amends,
            }

            # 4. Compute Record Hash & Digital Signature
            sign_bytes = signing_bytes(doc_payload)
            rec_hash = compute_record_hash(prev_hash, sign_bytes)

            if not signature:
                raw_sig = signing.sign(self._server_priv, sign_bytes)
                final_sig = f"ed25519:{raw_sig}"
            elif signature.startswith("ed25519:"):
                final_sig = signature
            else:
                final_sig = f"ed25519:{signature}"

            doc = {
                "seq": seq,
                "event_id": event_id,
                "box_id": box_id,
                "session_id": session_id,
                "ts": ts,
                "timestamp": ts,
                "status": status,
                "denomination": denom,
                "confidence": round(conf, 4),
                "model_version": model_version,
                "frame_sha": frame_sha,
                "frame_sha256": frame_sha,
                "prev_hash": prev_hash,
                "record_hash": rec_hash,
                "signature": final_sig,
                "thresholds": payload.get("thresholds", {}),
                "items": items,
                "amends": amends,
            }

            # 5. Strictly APPEND (insert_one only - no update or delete path exists)
            self.events.insert_one(doc)

            # Store item metadata in event_items collection
            if items:
                item_docs = []
                for it in items:
                    item_docs.append({
                        "event_id": event_id,
                        "seq": seq,
                        "label": str(it.get("label", denom)),
                        "conf": float(it.get("conf", conf)),
                        "decision": str(it.get("decision", status)),
                        "reason": it.get("reason", "model_prediction"),
                        "bbox": it.get("bbox", [0, 0, 0, 0]),
                        "aspect_ratio": it.get("aspect_ratio", 2.1)
                    })
                self.event_items.insert_many(item_docs)

            doc["_id"] = str(doc["_id"])
            return doc, True

    # =========================================================
    # Cryptographic Chain Verification & External Anchor
    # =========================================================
    def verify_chain(self) -> VerifyResult:
        """Walks the entire ledger from seq 1 to N, verifying hashes and signatures."""
        with self._lock:
            all_events = list(self.events.find({}, sort=[("seq", 1)]))
            if not all_events:
                return VerifyResult(ok=True, checked=0)

            keys_map = self.keys()
            server_pub = keys_map.get(SERVER_BOX, "")
            prev_expected = GENESIS

            for i, evt in enumerate(all_events):
                seq = evt["seq"]
                if seq != i + 1:
                    return VerifyResult(
                        ok=False, checked=i, first_bad_seq=seq,
                        reason=f"Broken sequence continuity: expected #{i + 1}, got #{seq}"
                    )

                if evt["prev_hash"] != prev_expected:
                    return VerifyResult(
                        ok=False, checked=i, first_bad_seq=seq,
                        reason=f"Hash chain broken at seq #{seq}: prev_hash does not match parent record_hash"
                    )

                sign_bytes = signing_bytes(evt)
                recomputed_hash = compute_record_hash(prev_expected, sign_bytes)

                if evt["record_hash"] != recomputed_hash:
                    return VerifyResult(
                        ok=False, checked=i, first_bad_seq=seq,
                        reason=f"Record content corrupted at seq #{seq}: payload hash mismatch"
                    )

                # Signature verification
                sig_str = evt.get("signature", "")
                raw_sig = sig_str.split(":", 1)[1] if sig_str.startswith("ed25519:") else sig_str
                pub_key = keys_map.get(evt["box_id"], server_pub)
                if not signing.verify(pub_key, sign_bytes, raw_sig):
                    return VerifyResult(
                        ok=False, checked=i, first_bad_seq=seq,
                        reason=f"Digital signature forged or invalid at seq #{seq}"
                    )

                prev_expected = evt["record_hash"]

            return VerifyResult(ok=True, checked=len(all_events))

    def export_chain_head(self, out_path: str = "data/chain_anchor.json") -> dict:
        """Exports the latest chain head to an external trust anchor file."""
        with self._lock:
            head = self.events.find_one(sort=[("seq", -1)])
            anchor = {
                "exported_at": _now(),
                "head_seq": head["seq"] if head else 0,
                "head_hash": head["record_hash"] if head else GENESIS,
                "events_count": self.events.count_documents({}),
                "server_box": SERVER_BOX
            }
            p = Path(out_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(anchor, indent=2))
            return anchor

    # =========================================================
    # Receipts & Review Queue Resolutions
    # =========================================================
    def create_receipt(self, event_id: str, donor_name: str = "Anonymous Donor") -> dict:
        """Generates an immutable donation receipt anchored to a ledger event."""
        with self._lock:
            evt = self.events.find_one({"event_id": event_id})
            if not evt:
                raise LedgerError(f"Event '{event_id}' not found in ledger")

            receipt_id = f"rcp-{uuid.uuid4().hex[:12]}"
            seq = evt["seq"]
            date_str = datetime.now().strftime("%Y%m%d")
            receipt_number = f"RCP-{date_str}-{seq:04d}"

            receipt_doc = {
                "receipt_id": receipt_id,
                "receipt_number": receipt_number,
                "event_id": evt["event_id"],
                "session_id": evt["session_id"],
                "denomination": evt["denomination"],
                "status": evt["status"],
                "timestamp": _now(),
                "ledger_hash": evt["record_hash"],
                "donor_name": donor_name,
                "box_id": evt["box_id"]
            }
            self.receipts.insert_one(receipt_doc)
            receipt_doc["_id"] = str(receipt_doc["_id"])
            return receipt_doc

    def verify_receipt(self, receipt_id: str) -> dict:
        """Verifies an individual receipt against its underlying ledger event hash."""
        with self._lock:
            rec = self.receipts.find_one(
                {"$or": [{"receipt_id": receipt_id}, {"receipt_number": receipt_id}]},
                {"_id": 0}
            )
            if not rec:
                return {"ok": False, "reason": f"Receipt '{receipt_id}' not found"}

            evt = self.events.find_one({"event_id": rec["event_id"]}, {"_id": 0})
            if not evt:
                return {"ok": False, "reason": "Underlying event not found in ledger"}

            if rec["ledger_hash"] != evt["record_hash"]:
                return {
                    "ok": False,
                    "reason": "Receipt hash mismatch: does not match cryptographic ledger block hash"
                }

            chain_check = self.verify_chain()
            return {
                "ok": chain_check.ok,
                "reason": None if chain_check.ok else (chain_check.reason or "Chain verification failed"),
                "receipt": rec,
                "event_seq": evt["seq"],
                "ledger_hash": evt["record_hash"],
                "chain_status": "PASS" if chain_check.ok else "CORRUPTED"
            }

    def resolve_review_item(self, event_id: str, new_label: str, by_user: str, note: str = "") -> dict:
        """Appends a new amendment event to resolve a flagged item. Never modifies original."""
        with self._lock:
            original = self.events.find_one({"event_id": event_id})
            if not original:
                raise LedgerError("Original event not found")

            # Prevent double-resolution
            if self.events.find_one({"amends": event_id}):
                raise LedgerError("Event already resolved by another amendment")

            is_reject = new_label.lower() in ("non_currency", "background", "reject")
            new_status = "rejected" if is_reject else "accepted"
            items = [] if is_reject else [{"label": new_label, "conf": 1.0, "decision": "ACCEPT", "reason": "auditor_override"}]

            amend_payload = {
                "event_id": f"amd-{uuid.uuid4().hex[:12]}",
                "box_id": SERVER_BOX,
                "session_id": original["session_id"],
                "status": new_status,
                "denomination": "non_currency" if is_reject else new_label,
                "confidence": 1.0,
                "model_version": f"auditor-override-{by_user}",
                "frame_sha256": original.get("frame_sha256") or original.get("frame_sha", ""),
                "frame_sha": original.get("frame_sha256") or original.get("frame_sha", ""),
                "items": items,
                "amends": original["event_id"],
            }
            amend_event, _ = self.ingest(amend_payload)

            self.feedback.insert_one({
                "event_id": amend_event["event_id"],
                "amends": original["event_id"],
                "timestamp": _now(),
                "by_user": by_user,
                "original_label": original.get("denomination", ""),
                "corrected_label": new_label,
                "note": note or "Auditor confirmed resolution"
            })
            return amend_event

    def resolve(self, event_id: str, corrected_items: list[dict] | list[str] | str, by_user: str, note: str = "") -> dict:
        """Compatibility alias for ledger.resolve."""
        if isinstance(corrected_items, list):
            if corrected_items and isinstance(corrected_items[0], dict):
                chosen = corrected_items[0].get("label", "100")
            elif corrected_items:
                chosen = str(corrected_items[0])
            else:
                chosen = "non_currency"
        else:
            chosen = str(corrected_items)
        return self.resolve_review_item(event_id, chosen, by_user, note)
