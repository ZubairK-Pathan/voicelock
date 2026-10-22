"""
tests/test_admin_mappings_api.py — Targeted test suite for Administrator Identity Mapping API endpoints.

Verifies:
1. Administrator list, link, and unlink success workflows.
2. Unauthenticated requests are rejected with HTTP 401.
3. Non-administrator requests are rejected with HTTP 403.
4. Duplicate Firebase UID assignment is rejected with HTTP 409.
5. Duplicate speaker assignment is rejected with HTTP 409.
6. Missing speaker returns HTTP 404.
7. Inactive or suspended speaker returns HTTP 400.
8. Nonexistent mapping ID on deletion returns HTTP 404.
9. Speaker record and biometric embedding are strictly preserved after unlinking.
10. Administrative security events are created in security_events table for successful mutations.
11. Atomic transaction rollback if audit logging fails during link or unlink.
12. Data minimization: Biometric vectors, secret hashes, and credentials are never leaked.
"""

import json
from unittest.mock import patch
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import set_test_token_verifier
from app.db.base import Base, SecurityEvent, SpeakerRecord, UserSpeakerMapping
from app.db.session import get_engine, get_db_context
from app.repositories.speaker_repository import SpeakerRepository
from app.repositories.user_speaker_repository import UserSpeakerRepository
from tests.test_auth import (
    ADMIN_TOKEN,
    USER_TOKEN,
    REVOKED_TOKEN,
    EXPIRED_TOKEN,
    INVALID_TOKEN,
    deterministic_test_verifier,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_auth_and_db():
    set_test_token_verifier(deterministic_test_verifier)
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with get_db_context() as session:
        # Clean mappings, events, and test speakers before each test
        session.query(UserSpeakerMapping).delete()
        session.query(SecurityEvent).delete()
        session.query(SpeakerRecord).delete()
    yield
    with get_db_context() as session:
        session.query(UserSpeakerMapping).delete()
        session.query(SecurityEvent).delete()
        session.query(SpeakerRecord).delete()


def test_list_mappings_empty_as_admin():
    """Admin query on empty mappings table returns HTTP 200 with empty list."""
    response = client.get("/admin/mappings", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert data["mappings"] == []
    assert data["count"] == 0


def test_list_mappings_unauthenticated_returns_401():
    """Unauthenticated access to /admin/mappings is rejected with HTTP 401."""
    response = client.get("/admin/mappings")
    assert response.status_code == 401
    assert "Authorization" in response.json()["detail"]


def test_list_mappings_non_admin_returns_403():
    """Ordinary user access to /admin/mappings is rejected with HTTP 403."""
    response = client.get("/admin/mappings", headers={"Authorization": f"Bearer {USER_TOKEN}"})
    assert response.status_code == 403
    assert "Administrative privileges required" in response.json()["detail"]


def test_list_unmapped_speakers_as_admin():
    """Admin query returns active speakers that do not yet have a user mapping."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        spk_repo.create(speaker_id="Alice", full_name="Alice Anderson", status="active")
        spk_repo.create(speaker_id="Bob", full_name="Bob Builder", status="active")
        spk_repo.create(speaker_id="Eve", full_name="Eve Suspended", status="suspended")

        # Map Alice to a user
        usr_repo.create(firebase_uid="uid-alice", speaker_id="Alice")

    response = client.get(
        "/admin/mappings/unmapped-speakers",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    unmapped_names = [s["speaker_id"] for s in data["unmapped_speakers"]]
    assert unmapped_names == ["Bob"]
    assert data["unmapped_speakers"][0]["full_name"] == "Bob Builder"
    assert data["unmapped_speakers"][0]["status"] == "active"


def test_create_mapping_success_and_audit_event():
    """Admin successfully links a Firebase UID to an active speaker and an audit event is logged."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair", full_name="Zubair Pathan", status="active", sample_count=5)

    payload = {
        "firebase_uid": "firebase-uid-zubair-123",
        "speaker_id": "Zubair",
        "notes": "Verified enterprise engineer",
    }
    response = client.post(
        "/admin/mappings",
        json=payload,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert "Successfully linked" in data["message"]
    mapping_data = data["mapping"]
    assert mapping_data["firebase_uid"] == "firebase-uid-zubair-123"
    assert mapping_data["speaker_id"] == "Zubair"
    assert mapping_data["speaker_name"] == "Zubair Pathan"
    assert mapping_data["sample_count"] == 5

    # Verify database persistence
    with get_db_context() as session:
        usr_repo = UserSpeakerRepository(session)
        mapping = usr_repo.get_by_firebase_uid("firebase-uid-zubair-123")
        assert mapping is not None
        assert mapping.speaker_id == "Zubair"

        # Verify audit trail
        events = session.query(SecurityEvent).filter(SecurityEvent.event_type == "admin_action").all()
        assert len(events) == 1
        event = events[0]
        assert event.status == "logged"
        assert event.severity == "low"
        assert "Linked user 'firebase-uid-zubair-123' to speaker 'Zubair'" in event.details
        meta = json.loads(event.metadata_json)
        assert meta["action"] == "link_user_speaker"
        assert meta["firebase_uid"] == "firebase-uid-zubair-123"
        assert meta["speaker_id"] == "Zubair"


def test_create_mapping_duplicate_uid_rejected():
    """Attempting to map a user that already has a speaker identity yields HTTP 409."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair")
        spk_repo.create(speaker_id="Omar")
        usr_repo.create(firebase_uid="uid-already-mapped", speaker_id="Zubair")

    response = client.post(
        "/admin/mappings",
        json={"firebase_uid": "uid-already-mapped", "speaker_id": "Omar"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 409
    assert "already mapped to speaker 'Zubair'" in response.json()["detail"]


def test_create_mapping_duplicate_speaker_rejected():
    """Attempting to assign a speaker identity that is already mapped yields HTTP 409."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair")
        usr_repo.create(firebase_uid="uid-first", speaker_id="Zubair")

    response = client.post(
        "/admin/mappings",
        json={"firebase_uid": "uid-second", "speaker_id": "Zubair"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 409
    assert "already assigned to account 'uid-first'" in response.json()["detail"]


def test_create_mapping_nonexistent_speaker_rejected():
    """Attempting to link to an unknown speaker yields HTTP 404."""
    response = client.post(
        "/admin/mappings",
        json={"firebase_uid": "uid-test", "speaker_id": "NonexistentSpeaker"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 404
    assert "not found in registry" in response.json()["detail"]


def test_create_mapping_inactive_speaker_rejected():
    """Attempting to link to a suspended speaker yields HTTP 400."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        spk_repo.create(speaker_id="SuspendedSpeaker", status="suspended")

    response = client.post(
        "/admin/mappings",
        json={"firebase_uid": "uid-test", "speaker_id": "SuspendedSpeaker"},
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 400
    assert "is not active" in response.json()["detail"]


def test_create_mapping_non_admin_rejected():
    """Ordinary users cannot create user-speaker mappings (HTTP 403)."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair")

    response = client.post(
        "/admin/mappings",
        json={"firebase_uid": "uid-test", "speaker_id": "Zubair"},
        headers={"Authorization": f"Bearer {USER_TOKEN}"},
    )
    assert response.status_code == 403


def test_delete_mapping_success_and_preserves_speaker_embedding():
    """Unlinking a mapping removes only the mapping row and preserves the speaker and embedding."""
    dummy_vec = np.ones(192, dtype=np.float32)
    dummy_vec /= np.linalg.norm(dummy_vec)

    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        spk = spk_repo.create(
            speaker_id="Zubair",
            full_name="Zubair Pathan",
            status="active",
            embedding=dummy_vec,
        )
        mapping = usr_repo.create(firebase_uid="uid-zubair", speaker_id="Zubair")
        mapping_id = mapping.id

    # Call DELETE /admin/mappings/{mapping_id}
    response = client.delete(
        f"/admin/mappings/{mapping_id}",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "Successfully unlinked" in response.json()["message"]

    # Verify: mapping is deleted
    with get_db_context() as session:
        usr_repo = UserSpeakerRepository(session)
        assert usr_repo.get_by_id(mapping_id) is None
        assert usr_repo.get_by_firebase_uid("uid-zubair") is None

        # Verify: SpeakerRecord and embedding are STILL INTACT!
        spk_repo = SpeakerRepository(session)
        preserved_spk = spk_repo.get_by_speaker_id("Zubair")
        assert preserved_spk is not None
        assert preserved_spk.full_name == "Zubair Pathan"
        assert preserved_spk.status == "active"
        stored_emb = spk_repo.get_embedding("Zubair")
        assert stored_emb is not None
        assert np.allclose(stored_emb, dummy_vec, atol=1e-6)

        # Verify: Audit event logged
        events = session.query(SecurityEvent).filter(SecurityEvent.event_type == "admin_action").all()
        assert len(events) == 1
        assert "Unlinked user 'uid-zubair' from speaker 'Zubair'" in events[0].details


def test_delete_nonexistent_mapping_rejected():
    """Attempting to delete a nonexistent mapping ID yields HTTP 404."""
    response = client.delete(
        "/admin/mappings/99999",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert response.status_code == 404
    assert "User-speaker mapping 99999 not found" in response.json()["detail"]


def test_delete_mapping_non_admin_rejected():
    """Non-admin user cannot delete user-speaker mappings (HTTP 403)."""
    response = client.delete(
        "/admin/mappings/1",
        headers={"Authorization": f"Bearer {USER_TOKEN}"},
    )
    assert response.status_code == 403


def test_create_mapping_rolls_back_if_audit_fails():
    """If recording the audit event fails, the entire transaction rolls back and no mapping is created."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair", status="active")

    # Simulate audit event insertion failure
    with patch("app.api.routes_admin_mappings.SecurityEvent", side_effect=RuntimeError("Audit journal disk error")):
        response = client.post(
            "/admin/mappings",
            json={"firebase_uid": "uid-fail-audit", "speaker_id": "Zubair"},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert response.status_code == 500
        assert "Database failure" in response.json()["detail"]

    # Verify mapping was NOT persisted
    with get_db_context() as session:
        usr_repo = UserSpeakerRepository(session)
        assert usr_repo.get_by_firebase_uid("uid-fail-audit") is None


def test_delete_mapping_rolls_back_if_audit_fails():
    """If recording the audit event fails during unlinking, the deletion is rolled back."""
    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair", status="active")
        mapping = usr_repo.create(firebase_uid="uid-keep-on-fail", speaker_id="Zubair")
        mapping_id = mapping.id

    with patch("app.api.routes_admin_mappings.SecurityEvent", side_effect=RuntimeError("Audit journal disk error")):
        response = client.delete(
            f"/admin/mappings/{mapping_id}",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert response.status_code == 500

    # Verify mapping still exists in database
    with get_db_context() as session:
        usr_repo = UserSpeakerRepository(session)
        assert usr_repo.get_by_id(mapping_id) is not None
        assert usr_repo.get_by_firebase_uid("uid-keep-on-fail") is not None


def test_data_minimization_no_sensitive_fields_in_responses():
    """Strictly verify that biometric embeddings, secret hashes, and tokens are never in responses."""
    dummy_vec = np.ones(192, dtype=np.float32)
    dummy_vec /= np.linalg.norm(dummy_vec)

    with get_db_context() as session:
        spk_repo = SpeakerRepository(session)
        usr_repo = UserSpeakerRepository(session)
        spk_repo.create(speaker_id="Zubair", status="active", embedding=dummy_vec)
        usr_repo.create(firebase_uid="uid-audit-check", speaker_id="Zubair")

    resp1 = client.get("/admin/mappings", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    text1 = resp1.text.lower()
    assert "embedding" not in text1
    assert "secret" not in text1
    assert "password" not in text1

    resp2 = client.get("/admin/mappings/unmapped-speakers", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    text2 = resp2.text.lower()
    assert "embedding" not in text2
    assert "secret" not in text2


def test_cors_preflight_allows_delete_method():
    """Verify OPTIONS preflight allows DELETE method for approved origins."""
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "authorization",
    }
    response = client.options("/admin/mappings/1", headers=headers)
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    allowed_methods = [m.strip() for m in response.headers.get("access-control-allow-methods", "").split(",")]
    assert "DELETE" in allowed_methods
    assert "GET" in allowed_methods
    assert "POST" in allowed_methods


def test_cors_preflight_allows_delete_method_production_frontend():
    """Verify OPTIONS preflight allows DELETE method for the production frontend origin."""
    prod_origin = "https://proud-glacier-03b4ad100.3.azurestaticapps.net"
    with patch.dict("os.environ", {"ALLOWED_CORS_ORIGINS": prod_origin}):
        from app.main import create_app
        prod_app = create_app()
        prod_client = TestClient(prod_app)
        headers = {
            "Origin": prod_origin,
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "authorization",
        }
        response = prod_client.options("/admin/mappings/1", headers=headers)
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == prod_origin
        allowed_methods = [m.strip() for m in response.headers.get("access-control-allow-methods", "").split(",")]
        assert "DELETE" in allowed_methods
        assert "GET" in allowed_methods
        assert "POST" in allowed_methods


def test_cors_preflight_rejects_unapproved_origin():
    """Verify OPTIONS preflight does not grant CORS access to unapproved origins."""
    headers = {
        "Origin": "https://malicious-unapproved-site.example.com",
        "Access-Control-Request-Method": "DELETE",
        "Access-Control-Request-Headers": "authorization",
    }
    response = client.options("/admin/mappings/1", headers=headers)
    assert response.headers.get("access-control-allow-origin") is None


def test_unauthenticated_delete_returns_401():
    """Verify unauthenticated DELETE /admin/mappings/{id} returns 401 before handler execution."""
    response = client.delete("/admin/mappings/999")
    assert response.status_code == 401
    assert "Missing Authorization header" in response.json().get("detail", "")
