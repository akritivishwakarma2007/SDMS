import pytest
from sdms.core.ledger import Ledger, generate_keypair
from sdms.core.pipeline import BoxPipeline
from sdms.core.policy import PolicyConfig
from sdms.core.sources.interfaces import Frame, SimClock
from sdms.core.vision.detector import MockDetector


@pytest.fixture
def ledger():
    return Ledger(":memory:")


@pytest.fixture
def box(ledger):
    priv, pub = generate_keypair()
    ledger.register_box("box-1", pub)
    return BoxPipeline("box-1", priv, MockDetector(seed=3, confusion_rate=0), PolicyConfig(), SimClock(), "s1")
