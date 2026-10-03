import hashlib, json

GENESIS = "0" * 64


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hex(b: bytes | str) -> str:
    if isinstance(b, str):
        b = b.encode()
    return hashlib.sha256(b).hexdigest()


def record_hash(prev: str, seq: int, ts: str, box_id: str, items: list, frame_sha: str,
                status: str, event_id: str, amends: str | None) -> str:
    """H_i = SHA-256(H_{i-1} || seq || ts || box || items || frame_sha || status ...).
    Fields are joined as a canonical JSON list so the encoding is unambiguous (no separator tricks).
    event_id and amends are included so they cannot be swapped or re-pointed."""
    return sha256_hex(canonical([prev, seq, ts, box_id, items, frame_sha, status, event_id, amends or ""]))
