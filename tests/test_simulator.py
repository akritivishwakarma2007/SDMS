"""R2/R3/R5/R7 harness check. NOTE: uses MockDetector, so this validates the pipeline, not a trained model."""
from sdms.simulator.virtual_box import run_simulation


def test_200_drop_run():
    res, led = run_simulation(200, seed=7)
    s = res.summary()
    assert res.chain_ok
    assert s["duplicates_created"] == 0 and s["duplicates_sent"] > 0     # R5
    assert s["retries"] > 0                                               # network faults exercised
    assert s["auto_miscount_rate"] <= 0.01                                # R2 (mock model)
    assert s["non_currency_false_accept_rate"] <= 0.01                    # R3 (mock model)
    # R7: any silent miscount that slipped past the policy must surface as reconciliation variance
    assert (res.reconcile["variance_total"] != 0) == (res.auto_miscounts > 0)
    assert res.counts["REVIEW"] > 0 and res.reviews_resolved == res.counts["REVIEW"]


def test_clock_drift_does_not_break_chain():
    from sdms.simulator.virtual_box import Faults
    res, _ = run_simulation(50, seed=2, faults=Faults(clock_drift_s=-3600))
    assert res.chain_ok


def test_perfect_model_reconciles_to_zero():
    from sdms.core.vision.detector import MockDetector
    res, _ = run_simulation(200, seed=3, detector=MockDetector(seed=3, confusion_rate=0.0))
    assert res.auto_miscounts == 0 and res.reconcile["variance_total"] == 0 and res.reconcile["pending_review"] == 0
