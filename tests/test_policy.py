from sdms.core.policy import PolicyConfig, decide_frame, ACCEPT, REVIEW, REJECT
from sdms.core.vision.detector import Detection

CFG = PolicyConfig()
B = (0, 0, 300, 140)   # ratio ~2.1


def test_confident_note_accepted():
    s, items = decide_frame([Detection("500", 0.97, B)], CFG)
    assert s == ACCEPT and items[0]["reason"] == "confident"


def test_grey_zone_goes_to_review():
    assert decide_frame([Detection("500", 0.6, B)], CFG)[0] == REVIEW


def test_below_floor_and_non_currency_rejected():
    assert decide_frame([Detection("500", 0.1, B)], CFG)[0] == REJECT
    assert decide_frame([Detection("non_currency", 0.99, B)], CFG)[0] == REJECT


def test_odd_aspect_ratio_review():
    assert decide_frame([Detection("100", 0.99, (0, 0, 100, 100))], CFG)[0] == REVIEW


def test_overlap_review():
    a, b = Detection("100", 0.99, (0, 0, 300, 140)), Detection("50", 0.99, (20, 10, 320, 150))
    assert decide_frame([a, b], CFG)[0] == REVIEW


def test_empty_frame_rejected():
    assert decide_frame([], CFG)[0] == REJECT


def test_2000_disabled_by_default():
    assert decide_frame([Detection("2000", 0.99, B)], CFG)[0] == REJECT


def test_mixed_frame_counts_only_accepted():
    s, items = decide_frame([Detection("100", 0.99, (0, 0, 300, 140)), Detection("non_currency", 0.9, (400, 0, 700, 140))], CFG)
    assert s == ACCEPT and [i["decision"] for i in items] == [ACCEPT, REJECT]
