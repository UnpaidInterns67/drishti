from ai.face_verification.config import HEAD_TURN_FRAMES
from ai.face_verification.liveness import LivenessDetector


def detector_for_turn(direction="RIGHT"):
    detector = LivenessDetector.__new__(LivenessDetector)
    detector.state = "TURN_HEAD"
    detector.required_turn_direction = direction
    detector.turn_frames = 0
    detector.head_turn_detected = False
    detector.turn_direction = None
    return detector


def test_head_turn_tolerates_one_borderline_frame():
    detector = detector_for_turn()
    detector._process_head_turn(0.12)
    detector._process_head_turn(0.02)
    detector._process_head_turn(0.12)
    detector._process_head_turn(0.12)
    assert detector.state == "RETURN_CENTER"
    assert detector.head_turn_detected


def test_wrong_direction_cannot_complete_challenge():
    detector = detector_for_turn("RIGHT")
    for _ in range(HEAD_TURN_FRAMES + 3):
        detector._process_head_turn(-0.2)
    assert detector.state == "TURN_HEAD"
    assert not detector.head_turn_detected
