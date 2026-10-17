"""
tests/test_persistent_auth.py — Dedicated test suite for Persistent User-to-Speaker Authorization Enforcement (Milestone 3C.2c.2).

Validates all 9 security requirements:
1. Mapped user verifying their own speaker identity -> Allowed.
2. Unmapped user denied -> HTTP 403 Forbidden.
3. User attempting a different speaker identity denied -> HTTP 403 Forbidden.
4. Client-supplied UID or role cannot override verified principal.
5. Admin allowed according to existing explicit policy.
6. Database lookup failure denies access (Fail-closed HTTP 500).
7. Authorization rejection happens before audio persistence and ML inference.
8. Existing device-auth behavior remains correct (separate from user mappings).
9. Existing challenge and verification behavior does not regress.
"""

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.db.base import Base, SpeakerRecord, UserSpeakerMapping
from app.db.session import create_db_engine, get_engine, get_db_context, reset_engine
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import UserSpeakerRepository
from app.core.auth import set_test_token_verifier, AuthenticatedUser
from app.core.device_auth import set_test_device_registry, AuthenticatedDevice
from app.core.auth_policy import Role
from app.core.rate_limit import _challenge_limiter, _verify_limiter, _identify_limiter
from app.core.config import SERVER_THRESHOLD

client = TestClient(app)

DUMMY_WAV = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

TOKEN_MAPPED_ZUBAIR = "token-user-zubair"
TOKEN_MAPPED_OMAR = "token-user-omar"
TOKEN_UNMAPPED_BOB = "token-user-bob"
TOKEN_ADMIN = "token-admin-user"

UID_ZUBAIR = "uid-zubair-mapped-101"
UID_OMAR = "uid-omar-mapped-102"
UID_BOB = "uid-bob-unmapped-999"
UID_ADMIN = "uid-admin-master-001"


def persistent_auth_test_verifier(token: str, check_revoked: bool = False) -> dict:
    """Mock verifier returning verified claims for distinct test users."""
    if token == TOKEN_MAPPED_ZUBAIR:
        return {
            "uid": UID_ZUBAIR,
            "email": "zubair@voicelock.test",
            "email_verified": True,
            "admin": False,
            "auth_time": 1700000000,
        }
    elif token == TOKEN_MAPPED_OMAR:
        return {
            "uid": UID_OMAR,
            "email": "omar@voicelock.test",
            "email_verified": True,
            "admin": False,
            "auth_time": 1700000000,
        }
    elif token == TOKEN_UNMAPPED_BOB:
        return {
            "uid": UID_BOB,
            "email": "bob@voicelock.test",
            "email_verified": True,
            "admin": False,
            "auth_time": 1700000000,
        }
    elif token == TOKEN_ADMIN:
        return {
            "uid": UID_ADMIN,
            "email": "admin@voicelock.test",
            "email_verified": True,
            "admin": True,
            "auth_time": 1700000000,
        }
    raise ValueError(f"Unknown test token: {token}")


@pytest.fixture(autouse=True)
def setup_persistent_auth():
    """Seed test database and configure token verifier."""
    app.dependency_overrides.clear()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()
    set_test_token_verifier(persistent_auth_test_verifier)
    set_test_device_registry({"esp32-door-portal": {"secret": "secret123", "name": "Main Entrance"}})

    Base.metadata.create_all(get_engine())

    with get_db_context() as session:
        session.query(UserSpeakerMapping).delete()
        session.query(SpeakerRecord).delete()
        session.flush()

        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)

        # Zubair and Omar are registered in speaker_profiles/profiles.pkl
        spk_repo.create(speaker_id="Zubair", full_name="Zubair Pathan")
        spk_repo.create(speaker_id="Omar", full_name="Omar Tariq")

        usr_repo.create(firebase_uid=UID_ZUBAIR, speaker_id="Zubair", assigned_by="system")
        usr_repo.create(firebase_uid=UID_OMAR, speaker_id="Omar", assigned_by="system")

    yield

    with get_db_context() as session:
        session.query(UserSpeakerMapping).delete()
        session.query(SpeakerRecord).delete()

    set_test_token_verifier(None)
    set_test_device_registry(None)
    app.dependency_overrides.clear()
    _challenge_limiter.reset_for_testing()
    _verify_limiter.reset_for_testing()
    _identify_limiter.reset_for_testing()


# ─── 1. Mapped User Verifying Own Identity ─────────────────────────────────────

def test_mapped_user_verifying_own_speaker_identity():
    """Verify mapped user is authorized to request challenge and submit verification for their bound speaker."""
    headers = {"Authorization": f"Bearer {TOKEN_MAPPED_ZUBAIR}"}

    # 1. Request challenge bound to Zubair
    r_ch = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Zubair", "session_id": "sess-zubair-01"},
    )
    assert r_ch.status_code == 200
    ch_data = r_ch.json()
    assert ch_data["claimed_identity"] == "Zubair"
    challenge_id = ch_data["challenge_id"]

    # 2. Verify with mock liveness and verify functions
    with patch("app.api.routes_verification._get_run_liveness_check") as mock_live:
        mock_live.return_value = lambda path, digits: (True, "Digits matched", "one two three")
        with patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
            mock_verify.return_value = lambda **kwargs: {
                "is_accepted": True,
                "similarity": 0.88,
                "claimed_identity": "Zubair",
            }
            r_ver = client.post(
                "/verify",
                headers=headers,
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": challenge_id,
                    "session_id": "sess-zubair-01",
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV), "audio/wav")},
            )
            assert r_ver.status_code == 200
            data = r_ver.json()
            assert data["accepted"] is True
            assert data["action"] == "UNLOCK"
            assert data["claimed_identity"] == "Zubair"


# ─── 2. Unmapped User Denied ───────────────────────────────────────────────────

def test_unmapped_user_denied_on_challenge_and_verify():
    """Verify an authenticated user with no UserSpeakerMapping record is denied with HTTP 403."""
    headers = {"Authorization": f"Bearer {TOKEN_UNMAPPED_BOB}"}

    # Attempting /challenge with claimed identity
    r_ch = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Zubair", "session_id": "sess-bob-01"},
    )
    assert r_ch.status_code == 403
    assert "not mapped to an enrolled speaker identity" in r_ch.json()["detail"]

    # Attempting /challenge without claimed identity
    r_ch_unbound = client.post(
        "/challenge",
        headers=headers,
        json={"session_id": "sess-bob-02"},
    )
    assert r_ch_unbound.status_code == 403
    assert "not mapped to an enrolled speaker identity" in r_ch_unbound.json()["detail"]

    # Attempting /verify directly
    r_ver = client.post(
        "/verify",
        headers=headers,
        data={
            "claimed_identity": "Zubair",
            "challenge_id": "any-challenge-id",
            "session_id": "sess-bob-01",
        },
        files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV), "audio/wav")},
    )
    assert r_ver.status_code == 403
    assert "not mapped to an enrolled speaker identity" in r_ver.json()["detail"]


# ─── 3. User Attempting Different Speaker Identity Denied ──────────────────────

def test_user_attempting_different_speaker_identity_denied():
    """Verify a mapped user cannot verify a different enrolled speaker's identity."""
    headers = {"Authorization": f"Bearer {TOKEN_MAPPED_ZUBAIR}"}

    # Zubair attempting to challenge Omar (who is enrolled in profiles.pkl)
    r_ch = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Omar", "session_id": "sess-mismatch-01"},
    )
    assert r_ch.status_code == 403
    assert "only authorized to verify your own voice identity" in r_ch.json()["detail"]

    # Zubair attempting to verify Omar
    r_ver = client.post(
        "/verify",
        headers=headers,
        data={
            "claimed_identity": "Omar",
            "challenge_id": "any-challenge-id",
            "session_id": "sess-mismatch-01",
        },
        files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV), "audio/wav")},
    )
    assert r_ver.status_code == 403
    assert "only authorized to verify your own voice identity" in r_ver.json()["detail"]


# ─── 4. Client-Supplied UID or Role Cannot Override Verified Principal ────────

def test_client_supplied_uid_or_role_cannot_override_principal():
    """
    Verify client cannot tamper with authentication identity by sending
    client-supplied uid, role, or claims in query strings or form bodies.
    """
    # Unmapped Bob tries to spoof Zubair's UID and role=admin via query params and body
    headers = {"Authorization": f"Bearer {TOKEN_UNMAPPED_BOB}"}
    r = client.post(
        f"/challenge?uid={UID_ZUBAIR}&role=admin&is_admin=true",
        headers=headers,
        json={
            "claimed_identity": "Zubair",
            "session_id": "sess-tamper-01",
            "uid": UID_ZUBAIR,
            "role": "admin",
        },
    )
    assert r.status_code == 403
    assert "not mapped to an enrolled speaker identity" in r.json()["detail"]


# ─── 5. Admin Allowed According to Existing Explicit Policy ────────────────────

def test_admin_allowed_according_to_explicit_policy():
    """Verify administrator is permitted to challenge and verify any registered speaker."""
    headers = {"Authorization": f"Bearer {TOKEN_ADMIN}"}

    # Admin challenges Zubair
    r_ch1 = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Zubair", "session_id": "sess-admin-01"},
    )
    assert r_ch1.status_code == 200

    # Admin challenges Omar
    r_ch2 = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Omar", "session_id": "sess-admin-02"},
    )
    assert r_ch2.status_code == 200


# ─── 6. Database Lookup Failure Denies Access (Fail Closed) ────────────────────

def test_database_lookup_failure_denies_access_fail_closed():
    """
    Verify database operational error fails closed with HTTP 500
    without leaking internal error details or falling back to insecure defaults.
    """
    headers = {"Authorization": f"Bearer {TOKEN_MAPPED_ZUBAIR}"}

    with patch("app.repositories.user_speaker_repository.UserSpeakerRepository.get_speaker_id_for_user") as mock_lookup:
        mock_lookup.side_effect = OperationalError("SELECT ...", {}, Exception("Database connection lost"))

        r = client.post(
            "/challenge",
            headers=headers,
            json={"claimed_identity": "Zubair", "session_id": "sess-db-err"},
        )
        assert r.status_code == 500
        assert r.json()["detail"] == "Database authorization service unavailable."


# ─── 7. Authorization Rejection Happens Before Audio Persistence and Inference ──

def test_authorization_rejection_happens_before_audio_persistence_and_inference():
    """
    Verify unauthorized verification requests are rejected before saving audio to disk
    or allocating ML inference slots.
    """
    headers = {"Authorization": f"Bearer {TOKEN_UNMAPPED_BOB}"}

    with patch("app.api.routes_verification._get_save_upload") as mock_save:
        with patch("app.api.routes_verification._get_verify_speaker") as mock_verify:
            r = client.post(
                "/verify",
                headers=headers,
                data={
                    "claimed_identity": "Zubair",
                    "challenge_id": "any-challenge-id",
                    "session_id": "sess-early-reject",
                },
                files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV), "audio/wav")},
            )
            assert r.status_code == 403
            # Neither audio saving nor ML inference should be invoked
            mock_save.assert_not_called()
            mock_verify.assert_not_called()


# ─── 8. Existing Device Authentication Remains Correct ─────────────────────────

def test_existing_device_auth_behavior_remains_correct():
    """Verify hardware IoT devices can initiate verification for enrolled speakers without user mappings."""
    headers = {"X-Device-ID": "esp32-door-portal", "X-Device-Key": "secret123"}

    # Device creates challenge for Zubair
    r_ch = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Zubair", "session_id": "sess-device-01"},
    )
    assert r_ch.status_code == 200
    ch_data = r_ch.json()

    # Device submits verification for Zubair
    with patch("cloud_api.run_liveness_check", return_value=(False, "Liveness failed", "")):
        r_ver = client.post(
            "/verify",
            headers=headers,
            data={
                "claimed_identity": "Zubair",
                "challenge_id": ch_data["challenge_id"],
                "session_id": "sess-device-01",
            },
            files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV), "audio/wav")},
        )
        assert r_ver.status_code == 200
        assert r_ver.json()["accepted"] is False
        assert r_ver.json()["liveness_passed"] is False


# ─── 9. Existing Challenge and Verification Behavior Does Not Regress ──────────

def test_existing_challenge_and_verification_behavior_does_not_regress():
    """
    Verify challenge replay resistance and session matching remain intact
    alongside persistent authorization.
    """
    headers = {"Authorization": f"Bearer {TOKEN_MAPPED_ZUBAIR}"}

    r_ch = client.post(
        "/challenge",
        headers=headers,
        json={"claimed_identity": "Zubair", "session_id": "sess-regress-01"},
    )
    assert r_ch.status_code == 200
    challenge_id = r_ch.json()["challenge_id"]

    # Replaying with wrong session fails HTTP 400
    r_bad_sess = client.post(
        "/verify",
        headers=headers,
        data={
            "claimed_identity": "Zubair",
            "challenge_id": challenge_id,
            "session_id": "wrong-session",
        },
        files={"audio": ("test.wav", io.BytesIO(DUMMY_WAV), "audio/wav")},
    )
    assert r_bad_sess.status_code == 400
    assert "Session mismatch" in r_bad_sess.json()["detail"]
