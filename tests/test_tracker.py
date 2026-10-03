import pytest
from sdms.core.vision.detector import Detection
from sdms.core.vision.tracker import NoteTracker


def test_single_note_counted_only_once_over_multiple_frames():
    tracker = NoteTracker(stabilize_frames=2, confirm_frames=4, confirm_confidence=0.80)
    det = Detection("500", 0.95, (100.0, 100.0, 320.0, 210.0))

    # Frame 1: DETECTING
    out1 = tracker.update([det])
    assert out1[0]["state"] == "DETECTING"
    assert tracker.total_amount == 0

    # Frame 2: STABILIZING
    out2 = tracker.update([det])
    assert out2[0]["state"] == "STABILIZING"
    assert tracker.total_amount == 0

    # Frame 3: STABILIZING
    out3 = tracker.update([det])
    assert out3[0]["state"] == "STABILIZING"
    assert tracker.total_amount == 0

    # Frame 4: CONFIRMED -> Added to donation total
    out4 = tracker.update([det])
    assert out4[0]["state"] == "CONFIRMED"
    assert out4[0]["counted"] is True
    assert tracker.total_amount == 500
    assert tracker.confirmed_counts["500"] == 1

    # Frames 5 to 15: Note remains in camera view
    for _ in range(10):
        out = tracker.update([det])
        assert out[0]["state"] == "CONFIRMED"
        # Total must REMAIN exactly 500 (no duplicate counts!)
        assert tracker.total_amount == 500
        assert tracker.confirmed_counts["500"] == 1


def test_multi_note_detection_and_running_total():
    tracker = NoteTracker(stabilize_frames=1, confirm_frames=2, confirm_confidence=0.80)
    note_500 = Detection("500", 0.96, (50.0, 50.0, 250.0, 150.0))
    note_200 = Detection("200", 0.94, (320.0, 50.0, 520.0, 150.0))
    note_100 = Detection("100", 0.92, (180.0, 220.0, 380.0, 320.0))

    frame_dets = [note_500, note_200, note_100]

    # Frame 1
    tracker.update(frame_dets)
    # Frame 2 -> all confirmed
    tracker.update(frame_dets)

    assert tracker.confirmed_counts["500"] == 1
    assert tracker.confirmed_counts["200"] == 1
    assert tracker.confirmed_counts["100"] == 1
    assert tracker.total_amount == 800


def test_uncertain_note_goes_to_review():
    tracker = NoteTracker(confirm_confidence=0.80)
    blurry_note = Detection("200", 0.62, (100.0, 100.0, 300.0, 200.0))

    # Multiple frames with 62% confidence -> REVIEW
    for _ in range(5):
        out = tracker.update([blurry_note])

    assert out[0]["state"] == "REVIEW"
    assert tracker.total_amount == 0  # Uncertain notes NEVER added automatically


def test_non_currency_rejected():
    tracker = NoteTracker()
    receipt = Detection("non_currency", 0.95, (100.0, 100.0, 250.0, 250.0))
    out = tracker.update([receipt])
    assert out[0]["state"] == "REJECT"
    assert tracker.total_amount == 0
