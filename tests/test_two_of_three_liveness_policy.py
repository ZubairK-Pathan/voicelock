"""
tests/test_two_of_three_liveness_policy.py — Comprehensive verification of the two-of-three-digit liveness policy.

Verifies all 9 requirements of the VoiceLock two-of-three-digit liveness specification:
1. All three digits correctly recognized.
2. Each valid two-digit subsequence (e.g., for challenge 709: 70, 09, 79).
3. Only one recognized digit (e.g., 7, 0, or 9 -> reject).
4. Incorrect digits (e.g., 12, 739 -> reject).
5. Out-of-order digits (e.g., 97 -> reject; matching is an ordered subsequence, not a set).
6. Correct challenge digits but failed speaker verification (similarity < 0.2500 -> DENY).
7. Matching speaker (similarity >= 0.2500) but failed liveness (-> DENY; speaker cannot bypass liveness).
8. Replay resistance via single-attempt invalidation ('burn-on-use' challenge token consumption).
9. Fail-closed final authorization decision: failed liveness can NEVER produce UNLOCK.
"""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedUser, get_current_admin, get_current_user
from app.core.auth_policy import Role
from app.core.config import SERVER_THRESHOLD
from app.core.device_auth import get_current_actor
from app.core.rate_limit import _challenge_limiter, _identify_limiter, _verify_limiter
from cloud_api import app
from liveness import is_ordered_subsequence, verify_liveness
from scripts.seed_speakers import run_seed_speakers

client = TestClient(app)

DUMMY_WAV_BYTES = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    b"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


@pytest.fixture(autouse=True)
def setup_test_auth_and_state():
    """Ensure database is seeded with valid speakers and auth dependencies are bound."""
    run_seed_speakers()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()

    admin_user = AuthenticatedUser(
        uid="test-admin-uid",
        email="admin@voicelock.test",
        email_verified=True,
        roles=[Role.ADMIN, Role.USER],
    )
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    app.dependency_overrides[get_current_actor] = lambda: admin_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_admin, None)
    app.dependency_overrides.pop(get_current_actor, None)
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()


# ==============================================================================
# Requirement 1, 2, 3, 4, 5: Challenge 709 Specification & Subsequence Verification
# ==============================================================================

def test_req1_all_three_digits_correctly_recognized():
    """Requirement 1: All three challenge digits spoken in order must pass liveness."""
    challenge = ["7", "0", "9"]
    passed, reason = verify_liveness("seven zero nine", challenge)
    assert passed is True
    assert "successfully" in reason.lower()

    # Formatted numeric string
    passed_num, _ = verify_liveness("709", challenge)
    assert passed_num is True


def test_req2_each_valid_two_digit_subsequence():
    """
    Requirement 2: Each valid two-digit ordered subsequence of 709 must pass liveness:
    - 70 (first two digits; last digit dropped)
    - 09 (last two digits; first digit clipped)
    - 79 (first and last digits; middle digit dropped)
    """
    challenge = ["7", "0", "9"]

    # Subsequence 1: 70 ("seven zero")
    passed_70, reason_70 = verify_liveness("seven zero", challenge)
    assert passed_70 is True
    assert "successfully" in reason_70.lower()
    assert "2 of 3" in reason_70

    # Subsequence 2: 09 ("zero nine" / "oh nine" / "o nine")
    passed_09, reason_09 = verify_liveness("zero nine", challenge)
    assert passed_09 is True
    assert "successfully" in reason_09.lower()
    assert "2 of 3" in reason_09

    passed_oh9, _ = verify_liveness("oh nine", challenge)
    assert passed_oh9 is True

    # Subsequence 3: 79 ("seven nine")
    passed_79, reason_79 = verify_liveness("seven nine", challenge)
    assert passed_79 is True
    assert "successfully" in reason_79.lower()
    assert "2 of 3" in reason_79

    # Numeric strings
    assert verify_liveness("70", challenge)[0] is True
    assert verify_liveness("09", challenge)[0] is True
    assert verify_liveness("79", challenge)[0] is True


def test_req3_only_one_recognized_digit_rejected():
    """Requirement 3: Only one recognized digit must be rejected (insufficient entropy)."""
    challenge = ["7", "0", "9"]

    for single in ["seven", "zero", "oh", "nine", "7", "0", "9"]:
        passed, reason = verify_liveness(single, challenge)
        assert passed is False
        assert "challenge failed" in reason.lower()
        assert "required at least 2" in reason.lower()


def test_req4_incorrect_digits_rejected():
    """Requirement 4: Spoken digits not matching the challenge sequence must be rejected."""
    challenge = ["7", "0", "9"]

    # Completely wrong digits (e.g. "12")
    passed_12, reason_12 = verify_liveness("one two", challenge)
    assert passed_12 is False
    assert "challenge failed" in reason_12.lower()

    # Wrong digits in 3-digit length (e.g. "739")
    passed_739, reason_739 = verify_liveness("seven three nine", challenge)
    assert passed_739 is False
    assert "challenge failed" in reason_739.lower()

    # Partial match with an incorrect intruder (e.g. "7 3")
    passed_73, reason_73 = verify_liveness("seven three", challenge)
    assert passed_73 is False
    assert "challenge failed" in reason_73.lower()

    # Extra digits beyond challenge length (e.g. "7 0 9 4")
    passed_extra, reason_extra = verify_liveness("seven zero nine four", challenge)
    assert passed_extra is False
    assert "challenge failed" in reason_extra.lower()


def test_req5_out_of_order_digits_rejected():
    """
    Requirement 5: Out-of-order digits must be rejected.
    Matching must strictly be an ordered subsequence, NOT an unordered set.
    """
    challenge = ["7", "0", "9"]

    # 97 (reverse order of 7 and 9)
    passed_97, reason_97 = verify_liveness("nine seven", challenge)
    assert passed_97 is False
    assert "challenge failed" in reason_97.lower()

    # 90 (reverse order of 0 and 9)
    passed_90, reason_90 = verify_liveness("nine zero", challenge)
    assert passed_90 is False
    assert "challenge failed" in reason_90.lower()

    # 07 (reverse order of 7 and 0)
    passed_07, reason_07 = verify_liveness("zero seven", challenge)
    assert passed_07 is False
    assert "challenge failed" in reason_07.lower()

    # 907 (full reverse)
    passed_907, reason_907 = verify_liveness("nine zero seven", challenge)
    assert passed_907 is False
    assert "challenge failed" in reason_907.lower()

    # Verify is_ordered_subsequence directly confirms strict temporal order
    assert is_ordered_subsequence(["9", "7"], challenge) is False
    assert is_ordered_subsequence(["0", "7"], challenge) is False
    assert is_ordered_subsequence(["7", "0"], challenge) is True


# ==============================================================================
# Requirement 6, 7, 8, 9: End-to-End Route Authorization & Security Invariants
# ==============================================================================

def test_req6_correct_challenge_digits_but_failed_speaker_verification():
    """
    Requirement 6: If challenge digits are correct (or valid 2-of-3 subsequence)
    but speaker verification fails (similarity < SERVER_THRESHOLD), access must be DENIED.
    """
    # Issue fresh challenge
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    # Mock liveness passing (2-of-3 valid subsequence), but speaker verification failing
    with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified successfully (2 of 3 digits matched in order).", "7 0")):
        with patch("cloud_api.verify_speaker", return_value={"is_accepted": False, "similarity": 0.1824}):
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["accepted"] is False
            assert data["action"] == "DENY"
            assert data["liveness_passed"] is True
            assert data["similarity"] == 0.1824
            assert data["threshold_used"] == SERVER_THRESHOLD


def test_req7_matching_speaker_but_failed_liveness_cannot_bypass():
    """
    Requirement 7: If speaker verification would accept (high similarity, e.g. 0.88),
    but liveness fails (e.g. wrong digits, out-of-order, or only 1 digit),
    access must be DENIED immediately without granting UNLOCK.
    Recognized digits must NEVER be accepted merely because the speaker matches.
    """
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    # Mock liveness failure: out-of-order "nine seven"
    with patch("cloud_api.run_liveness_check", return_value=(False, "Challenge failed: spoken digits did not match the required challenge sequence.", "nine seven")):
        with patch("cloud_api.verify_speaker") as mock_verify:
            response = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["accepted"] is False
            assert data["action"] == "DENY"
            assert data["liveness_passed"] is False
            assert "liveness check failed" in data["reason"].lower()
            # Security boundary: Biometric inference must be completely skipped
            mock_verify.assert_not_called()


def test_req8_replay_and_reused_challenge_attempt_rejected():
    """
    Requirement 8: Replay attack prevention.
    A challenge token is burned atomically upon initial submission ('burn-on-use').
    Replaying audio or attempting to reuse the same challenge must be rejected with HTTP 400.
    """
    ch = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()

    with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified successfully (2 of 3 digits matched in order).", "7 0")):
        with patch("cloud_api.verify_speaker", return_value={"is_accepted": True, "similarity": 0.82}):
            # Attempt 1: Valid submission
            resp1 = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )
            assert resp1.status_code == 200
            assert resp1.json()["action"] == "UNLOCK"

            # Attempt 2: Replay attack using identical payload and challenge token
            resp2 = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch["challenge_id"],
                    "session_id": ch["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            )
            assert resp2.status_code == 400
            assert "already been consumed" in resp2.json()["detail"].lower()


def test_req9_final_authorization_decision_fail_closed_guarantee():
    """
    Requirement 9: Final authorization decision verification.
    Confirms that failed liveness can NEVER return UNLOCK under any condition.
    UNLOCK is granted strictly and only when BOTH liveness_passed == True AND similarity >= threshold.
    """
    # Sub-case A: 2-of-3 liveness passed + speaker verified -> UNLOCK
    ch_a = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()
    with patch("cloud_api.run_liveness_check", return_value=(True, "Liveness verified successfully (2 of 3 digits matched in order).", "7 9")):
        with patch("cloud_api.verify_speaker", return_value={"is_accepted": True, "similarity": 0.35}):
            res_a = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch_a["challenge_id"],
                    "session_id": ch_a["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            ).json()
            assert res_a["accepted"] is True
            assert res_a["action"] == "UNLOCK"
            assert res_a["liveness_passed"] is True

    # Sub-case B: Liveness failed (only 1 digit) + high speaker similarity (0.95) -> strictly DENY
    ch_b = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()
    with patch("cloud_api.run_liveness_check", return_value=(False, "Challenge failed: heard only 1 digit, required at least 2 challenge digits.", "7")):
        with patch("cloud_api.verify_speaker", return_value={"is_accepted": True, "similarity": 0.95}):
            res_b = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch_b["challenge_id"],
                    "session_id": ch_b["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            ).json()
            assert res_b["accepted"] is False
            assert res_b["action"] == "DENY"
            assert res_b["liveness_passed"] is False

    # Sub-case C: Liveness failed (out-of-order) + high speaker similarity (0.95) -> strictly DENY
    ch_c = client.post("/challenge", data={"claimed_identity": "Zubair"}).json()
    with patch("cloud_api.run_liveness_check", return_value=(False, "Challenge failed: spoken digits did not match the required challenge sequence.", "9 7")):
        with patch("cloud_api.verify_speaker", return_value={"is_accepted": True, "similarity": 0.95}):
            res_c = client.post(
                "/verify",
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": ch_c["challenge_id"],
                    "session_id": ch_c["session_id"],
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV_BYTES), "audio/wav")},
            ).json()
            assert res_c["accepted"] is False
            assert res_c["action"] == "DENY"
            assert res_c["liveness_passed"] is False

