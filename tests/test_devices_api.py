"""
tests/test_devices_api.py — Dedicated test suite for GET /devices endpoint.
Verifies administrative RBAC, data minimization, lifecycle status aggregation, and error handling.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.auth import set_test_token_verifier
from app.db.base import Base
from app.db.session import get_engine, get_db_context
from app.repositories.device_repository import DeviceRepository
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
        # Clean devices table before each test
        repo = DeviceRepository(session)
        for dev in repo.list_devices():
            session.delete(dev)
    yield
    with get_db_context() as session:
        repo = DeviceRepository(session)
        for dev in repo.list_devices():
            session.delete(dev)


def test_list_devices_empty_database_admin():
    """Admin query on empty database returns 200 with empty list and zero counts."""
    response = client.get("/devices", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert data["devices"] == []
    assert data["total"] == 0
    assert data["active_count"] == 0


def test_list_devices_with_records_and_status_filtering():
    """Admin query returns registered terminals with active counts and non-sensitive fields."""
    with get_db_context() as session:
        repo = DeviceRepository(session)
        repo.create(
            device_id="esp32-portal-01",
            secret_hash="sha256$e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            name="Front Gate Terminal",
            status="active",
            key_version=1,
        )
        repo.create(
            device_id="esp32-portal-02",
            secret_hash="sha256$e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            name="Lab Entrance",
            status="suspended",
            key_version=2,
        )

    response = client.get("/devices", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["active_count"] == 1
    assert len(data["devices"]) == 2

    dev_map = {d["device_id"]: d for d in data["devices"]}
    assert "esp32-portal-01" in dev_map
    assert dev_map["esp32-portal-01"]["name"] == "Front Gate Terminal"
    assert dev_map["esp32-portal-01"]["status"] == "active"
    assert dev_map["esp32-portal-01"]["key_version"] == 1

    assert "esp32-portal-02" in dev_map
    assert dev_map["esp32-portal-02"]["name"] == "Lab Entrance"
    assert dev_map["esp32-portal-02"]["status"] == "suspended"


def test_list_devices_data_minimization():
    """Strictly verifies that secret_hash is NEVER exposed in the JSON response payload."""
    secret_hash_value = "sha256$super_secret_never_leak_this_hash_12345678"
    with get_db_context() as session:
        repo = DeviceRepository(session)
        repo.create(
            device_id="esp32-secure-01",
            secret_hash=secret_hash_value,
            name="Restricted Vault",
            status="active",
        )

    response = client.get("/devices", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    raw_text = response.text
    assert "secret_hash" not in raw_text
    assert secret_hash_value not in raw_text
    assert "super_secret" not in raw_text

    item = response.json()["devices"][0]
    assert set(item.keys()) == {"device_id", "name", "status", "key_version"}


def test_list_devices_forbidden_for_ordinary_user():
    """Ordinary authenticated users (Role.USER) are rejected with HTTP 403 Forbidden."""
    response = client.get("/devices", headers={"Authorization": f"Bearer {USER_TOKEN}"})
    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"] or "Admin role required" in response.json()["detail"]


def test_list_devices_unauthenticated():
    """Unauthenticated requests without headers are rejected with HTTP 401."""
    response = client.get("/devices")
    assert response.status_code == 401


def test_list_devices_invalid_or_expired_token():
    """Invalid or expired tokens are rejected with HTTP 401."""
    res_invalid = client.get("/devices", headers={"Authorization": f"Bearer {INVALID_TOKEN}"})
    assert res_invalid.status_code == 401

    res_expired = client.get("/devices", headers={"Authorization": f"Bearer {EXPIRED_TOKEN}"})
    assert res_expired.status_code == 401


def test_list_devices_revoked_admin_token():
    """Revoked admin tokens are rejected with HTTP 401 via check_revoked=True."""
    response = client.get("/devices", headers={"Authorization": f"Bearer {REVOKED_TOKEN}"})
    assert response.status_code == 401


def test_list_devices_database_failure_fails_closed():
    """Database failures return sanitized HTTP 500 without leaking stack trace."""
    with patch("app.api.routes_devices.DeviceRepository.list_devices", side_effect=RuntimeError("DB disk failure")):
        response = client.get("/devices", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
        assert response.status_code == 500
        assert "Database failure while retrieving device registry." in response.json()["detail"]
        assert "DB disk failure" not in response.text
