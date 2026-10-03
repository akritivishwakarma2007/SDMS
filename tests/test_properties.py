from hypothesis import given, settings, strategies as st, HealthCheck
from sdms.core.ledger import Ledger, generate_keypair
from sdms.core.pipeline import BoxPipeline
from sdms.core.policy import PolicyConfig
from sdms.core.sources.interfaces import Frame, SimClock
from sdms.core.vision.detector import MockDetector


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.tuples(st.sampled_from(["10", "20", "50", "100", "200", "500", "non_currency"]),
                          st.sampled_from(["ok", "blur", "dark"])), min_size=0, max_size=25))
def test_chain_verifies_after_any_sequence(seq):
    led = Ledger(":memory:"); priv, pub = generate_keypair(); led.register_box("b", pub)
    box = BoxPipeline("b", priv, MockDetector(seed=1), PolicyConfig(), SimClock(), "s")
    for i, (lab, q) in enumerate(seq):
        led.ingest(*box.process(Frame(f"f{i}".encode(), f"t{i}", {"truth": [lab], "quality": q})))
    assert led.verify().ok
