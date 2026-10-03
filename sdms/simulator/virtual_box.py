"""Virtual donation box: replays synthetic drops through the real pipeline with fault injection."""
from __future__ import annotations
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sdms.core.ledger import Ledger, LedgerError, generate_keypair
from sdms.core.pipeline import BoxPipeline
from sdms.core.policy import PolicyConfig
from sdms.core.sources.interfaces import Frame, SimClock
from sdms.core.vision.detector import MockDetector

DENOMS = ["10", "20", "50", "100", "200", "500"]


@dataclass
class Faults:
    p_two_note: float = 0.25
    p_blur: float = 0.05
    p_dark: float = 0.05
    p_non_currency: float = 0.05
    p_duplicate: float = 0.05        # same event re-sent
    p_net_fail: float = 0.15         # a send attempt fails; box retries the same event_id
    clock_drift_s: float = 0.0
    max_retries: int = 5


@dataclass
class SimResult:
    drops: int = 0
    counts: Counter = field(default_factory=Counter)      # status counts
    auto_accepted: int = 0
    auto_miscounts: int = 0            # ACCEPT events whose counted notes != ground truth
    non_currency_false_accepts: int = 0
    non_currency_items: int = 0
    retries: int = 0
    duplicates_sent: int = 0
    duplicates_created: int = 0        # must stay 0
    reviews_resolved: int = 0
    chain_ok: bool = False
    reconcile: dict = field(default_factory=dict)

    def summary(self) -> dict:
        d = self.__dict__.copy()
        d["counts"] = dict(self.counts)
        d["auto_miscount_rate"] = self.auto_miscounts / self.auto_accepted if self.auto_accepted else 0.0
        d["non_currency_false_accept_rate"] = (self.non_currency_false_accepts / self.non_currency_items
                                                if self.non_currency_items else 0.0)
        return d


def run_simulation(n_drops: int = 200, seed: int = 1, faults: Faults | None = None,
                   ledger: Ledger | None = None, policy: PolicyConfig | None = None,
                   detector=None, resolve_reviews: bool = True) -> tuple[SimResult, Ledger]:
    faults = faults or Faults()
    rng = random.Random(seed)
    ledger = ledger or Ledger(":memory:")
    priv, pub = generate_keypair()
    ledger.register_box("box-1", pub)
    session = "sim-session"
    clock = SimClock(drift_s=faults.clock_drift_s)
    pipe = BoxPipeline("box-1", priv, detector or MockDetector(seed=seed), policy or PolicyConfig(), clock, session)
    res = SimResult()
    truth_by_event: dict[str, list[str]] = {}
    physical: Counter = Counter()

    def flaky_send(payload, sig):
        for attempt in range(faults.max_retries + 1):
            if rng.random() < faults.p_net_fail and attempt < faults.max_retries:
                res.retries += 1
                continue
            return ledger.ingest(payload, sig)
        raise LedgerError("gave up")

    for i in range(n_drops):
        r = rng.random()
        if r < faults.p_non_currency:
            truth = ["non_currency"]
        else:
            k = 2 if rng.random() < faults.p_two_note else 1
            truth = [rng.choice(DENOMS) for _ in range(k)]
        q = "blur" if rng.random() < faults.p_blur else "dark" if rng.random() < faults.p_dark else "ok"
        frame = Frame(f"sim-frame-{seed}-{i}-{rng.random()}".encode(), trigger_id=f"drop-{i:05d}",
                      meta={"truth": truth, "quality": q})
        payload, sig = pipe.process(frame)
        truth_by_event[payload["event_id"]] = truth
        physical.update(t for t in truth if t != "non_currency")
        res.non_currency_items += truth.count("non_currency")
        row, created = flaky_send(payload, sig)
        res.counts[payload["status"]] += 1
        if payload["status"] == "ACCEPT":
            res.auto_accepted += 1
            counted = sorted(it["label"] for it in payload["items"] if it["decision"] == "ACCEPT")
            if counted != sorted(t for t in truth if t != "non_currency"):
                res.auto_miscounts += 1
            res.non_currency_false_accepts += sum(1 for it, t in zip(payload["items"], truth)
                                                  if t == "non_currency" and it["decision"] == "ACCEPT")
        if rng.random() < faults.p_duplicate:
            res.duplicates_sent += 1
            _, created_again = ledger.ingest(payload, sig)
            res.duplicates_created += int(created_again)
        res.drops += 1

    if resolve_reviews:   # the auditor: fixes each REVIEW event using the truth (stands in for a human)
        for ev in ledger.review_queue():
            truth = [t for t in truth_by_event[ev["event_id"]] if t != "non_currency"]
            ledger.amend(ev["event_id"], [{"label": t, "decision": "ACCEPT", "reason": "human_confirmed"} for t in truth],
                         by_user="sim-auditor")
            res.reviews_resolved += 1
    ledger.close_session(session)
    res.chain_ok = ledger.verify().ok
    res.reconcile = ledger.reconcile(session, dict(physical), "sim-auditor")
    return res, ledger
