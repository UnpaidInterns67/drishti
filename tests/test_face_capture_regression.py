from unittest.mock import Mock, patch

import numpy as np

from ai.face_verification.verifier import IdentityVerifier


def verifier_with_results(results):
    with patch('ai.face_verification.verifier.FaceEngine'):
        verifier = IdentityVerifier()
    verifier.session_active = True
    verifier.id_embedding = np.array([1.0])
    verifier.face_engine.detect_faces.return_value = np.ones((1, 15))
    verifier.face_engine.confidence.return_value = 0.95
    verifier.face_engine.embedding.return_value = np.array([1.0])
    verifier.face_engine.cosine_similarity.return_value = 0.60
    verifier.quality_checker = Mock()
    verifier.quality_checker.evaluate.return_value = {'passed': True}
    verifier.liveness = Mock(open_ear_baseline=0.30)
    verifier.liveness.process.side_effect = results
    return verifier


def result(passed=True, yaw=0.0, ear=0.30):
    return {'passed': passed, 'state': 'PASSED' if passed else 'TURN_HEAD',
            'yaw_signal': yaw, 'ear': ear, 'score': 1.0}


def test_challenge_frames_never_enter_match_samples():
    verifier = verifier_with_results([result(False, 0.15)] * 4 + [result()] * 3)
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    for _ in range(4):
        response = verifier.process_frame(frame)
        assert not verifier.live_embedding_samples
        assert 'verification_passed' not in response
    for _ in range(2):
        assert verifier.process_frame(frame)['state'] == 'STABILIZING'
    response = verifier.process_frame(frame)
    assert response['verification_passed'] is True
    assert response['face_samples'] == 3
    assert verifier.face_engine.embedding.call_count == 3


def test_recognition_keeps_camera_orientation_and_only_liveness_is_mirrored():
    verifier = verifier_with_results([result()])
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    frame[:, :20, :] = 255
    verifier.process_frame(frame, mirror_liveness=True)
    np.testing.assert_array_equal(verifier.face_engine.embedding.call_args.args[0], frame)
    np.testing.assert_array_equal(verifier.liveness.process.call_args.args[0], frame[:, ::-1])


def test_turned_or_closed_eye_samples_reset_capture():
    verifier = verifier_with_results([result(), result(yaw=0.2), result(), result(ear=0.1)])
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    for expected in [1, 0, 1, 0]:
        assert verifier.process_frame(frame)['state'] == 'STABILIZING'
        assert len(verifier.live_embedding_samples) == expected


def test_low_similarity_still_fails_after_good_capture():
    verifier = verifier_with_results([result()] * 3)
    verifier.face_engine.cosine_similarity.return_value = 0.20
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    for _ in range(3):
        response = verifier.process_frame(frame)
    assert response['verification_passed'] is False
    assert response['face_match'] is False
