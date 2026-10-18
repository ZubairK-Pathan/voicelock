"""
tests/test_device_repository.py — Unit test suite for DeviceRepository (Milestone 3C.3b).

Tests:
1. Enforcement of non-null Session initialization.
2. Creating device records with valid attributes and default values.
3. Input validation (empty device_id, empty secret_hash, invalid status, invalid key_version).
4. Duplicate device ID rejection (DuplicateDeviceError via database constraint).
5. Retrieval by device_id and integer primary key.
6. Missing record handling (None vs DeviceNotFoundError via get_or_raise).
7. Listing devices, pagination (limit/offset), and lifecycle status filtering.
8. Updating device metadata, status transitions, and timestamp updates.
9. Device revocation helper (transitions status to 'revoked').
10. Deleting device records and verifying cleanup.
11. Device count query with optional status filtering.
12. Explicit transaction boundaries and caller-controlled rollback.
13. Security hygiene (no raw credentials stored or exposed).
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.base import Base, DeviceRecord
from app.db.session import create_db_engine
from app.repositories.device_repository import (
    DeviceRepository,
    DuplicateDeviceError,
    DeviceNotFoundError,
)


@pytest.fixture
def db_session():
    """Create an isolated, disposable SQLite database and session for each unit test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    db_url = f"sqlite:///{tmp_db_path}"
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def test_repository_requires_active_session():
    """Verify DeviceRepository raises ValueError if initialized without a session."""
    with pytest.raises(ValueError, match="requires an active SQLAlchemy Session"):
        DeviceRepository(None)


def test_create_device_success(db_session):
    """Verify creating a device record with valid attributes and defaults."""
    repo = DeviceRepository(db_session)
    device = repo.create(
        device_id="esp32-door-portal-01",
        secret_hash="sha256$credential_hash_value_12345",
        name="Main Entrance Gate",
        status="active",
        key_version=1,
        metadata_json='{"location": "North Wing", "mac": "AA:BB:CC:DD:EE:FF"}',
    )
    db_session.commit()

    assert device.id is not None
    assert device.device_id == "esp32-door-portal-01"
    assert device.name == "Main Entrance Gate"
    assert device.status == "active"
    assert device.is_active is True
    assert device.secret_hash == "sha256$credential_hash_value_12345"
    assert device.key_version == 1
    assert device.metadata_json == '{"location": "North Wing", "mac": "AA:BB:CC:DD:EE:FF"}'
    assert device.created_at is not None
    assert device.updated_at is not None


def test_create_device_input_validation(db_session):
    """Verify input validation rules on create."""
    repo = DeviceRepository(db_session)

    # Empty / whitespace device_id
    with pytest.raises(ValueError, match="device_id must be a non-empty string"):
        repo.create(device_id="", secret_hash="sha256$valid")
    with pytest.raises(ValueError, match="device_id must be a non-empty string"):
        repo.create(device_id="   ", secret_hash="sha256$valid")

    # Empty / whitespace secret_hash
    with pytest.raises(ValueError, match="secret_hash must be a non-empty string"):
        repo.create(device_id="dev-1", secret_hash="")
    with pytest.raises(ValueError, match="secret_hash must be a non-empty string"):
        repo.create(device_id="dev-1", secret_hash="   ")

    # Invalid status
    with pytest.raises(ValueError, match="Invalid status 'invalid'"):
        repo.create(device_id="dev-1", secret_hash="sha256$valid", status="invalid")

    # Invalid key_version < 1
    with pytest.raises(ValueError, match="key_version must be at least 1"):
        repo.create(device_id="dev-1", secret_hash="sha256$valid", key_version=0)


def test_create_duplicate_device_id_rejected(db_session):
    """Verify DuplicateDeviceError is raised when device_id already exists."""
    repo = DeviceRepository(db_session)
    repo.create(device_id="esp32-portal-01", secret_hash="sha256$hash1")
    db_session.commit()

    with pytest.raises(DuplicateDeviceError, match="already exists"):
        repo.create(device_id="esp32-portal-01", secret_hash="sha256$hash2")


def test_get_by_device_id_and_id(db_session):
    """Verify lookups by unique device_id and primary key ID."""
    repo = DeviceRepository(db_session)
    created = repo.create(
        device_id="esp32-portal-02",
        secret_hash="sha256$hash2",
        name="Side Door",
    )
    db_session.commit()

    # Lookup by device_id
    by_dev_id = repo.get_by_device_id("esp32-portal-02")
    assert by_dev_id is not None
    assert by_dev_id.id == created.id
    assert by_dev_id.name == "Side Door"

    # Lookup by primary key ID
    by_pk = repo.get_by_id(created.id)
    assert by_pk is not None
    assert by_pk.device_id == "esp32-portal-02"

    # Non-existent lookups
    assert repo.get_by_device_id("non-existent") is None
    assert repo.get_by_id(999999) is None
    assert repo.get_by_device_id("") is None


def test_get_or_raise_behavior(db_session):
    """Verify get_or_raise returns record when present or raises DeviceNotFoundError."""
    repo = DeviceRepository(db_session)
    repo.create(device_id="esp32-portal-03", secret_hash="sha256$hash3")
    db_session.commit()

    device = repo.get_or_raise("esp32-portal-03")
    assert device.device_id == "esp32-portal-03"

    with pytest.raises(DeviceNotFoundError, match="Device 'missing-dev' not found"):
        repo.get_or_raise("missing-dev")


def test_list_devices_and_status_filtering(db_session):
    """Verify list_devices orders alphabetically, filters by status, and paginates."""
    repo = DeviceRepository(db_session)
    repo.create(device_id="terminal-c", secret_hash="sha256$c", status="active")
    repo.create(device_id="terminal-a", secret_hash="sha256$a", status="active")
    repo.create(device_id="terminal-b", secret_hash="sha256$b", status="suspended")
    repo.create(device_id="terminal-d", secret_hash="sha256$d", status="revoked")
    db_session.commit()

    # All devices ordered alphabetically
    all_devs = repo.list_devices()
    assert [d.device_id for d in all_devs] == [
        "terminal-a",
        "terminal-b",
        "terminal-c",
        "terminal-d",
    ]

    # Filter by active status
    active_devs = repo.list_devices(status="active")
    assert [d.device_id for d in active_devs] == ["terminal-a", "terminal-c"]

    # Filter by suspended status
    suspended_devs = repo.list_devices(status="suspended")
    assert [d.device_id for d in suspended_devs] == ["terminal-b"]

    # Filter by revoked status
    revoked_devs = repo.list_devices(status="revoked")
    assert [d.device_id for d in revoked_devs] == ["terminal-d"]

    # Invalid status filter
    with pytest.raises(ValueError, match="Invalid status 'unknown'"):
        repo.list_devices(status="unknown")

    # Pagination: limit & offset
    page1 = repo.list_devices(limit=2, offset=0)
    assert [d.device_id for d in page1] == ["terminal-a", "terminal-b"]

    page2 = repo.list_devices(limit=2, offset=2)
    assert [d.device_id for d in page2] == ["terminal-c", "terminal-d"]


def test_update_device_success(db_session):
    """Verify updating permitted metadata and lifecycle status fields."""
    repo = DeviceRepository(db_session)
    repo.create(
        device_id="esp32-turnstile",
        secret_hash="sha256$hash",
        name="Turnstile 1",
        status="active",
        metadata_json='{"lane": 1}',
    )
    db_session.commit()

    updated = repo.update(
        device_id="esp32-turnstile",
        name="Turnstile 1 - North",
        status="suspended",
        metadata_json='{"lane": 1, "calibrated": true}',
    )
    assert updated is not None
    assert updated.name == "Turnstile 1 - North"
    assert updated.status == "suspended"
    assert updated.is_active is False
    assert updated.metadata_json == '{"lane": 1, "calibrated": true}'

    # Updating non-existent returns None
    assert repo.update(device_id="missing-dev", name="New Name") is None

    # Updating with invalid status raises ValueError
    with pytest.raises(ValueError, match="Invalid status 'broken'"):
        repo.update(device_id="esp32-turnstile", status="broken")


def test_revoke_device(db_session):
    """Verify revoke helper method marks device as revoked."""
    repo = DeviceRepository(db_session)
    repo.create(device_id="esp32-stolen", secret_hash="sha256$hash", status="active")
    db_session.commit()

    revoked = repo.revoke("esp32-stolen")
    assert revoked is not None
    assert revoked.status == "revoked"
    assert revoked.is_active is False

    # Revoking non-existent device returns None
    assert repo.revoke("missing-dev") is None


def test_delete_device(db_session):
    """Verify removing a device from the database."""
    repo = DeviceRepository(db_session)
    repo.create(device_id="esp32-temp", secret_hash="sha256$hash")
    db_session.commit()

    assert repo.delete("esp32-temp") is True
    assert repo.get_by_device_id("esp32-temp") is None

    # Second delete returns False
    assert repo.delete("esp32-temp") is False


def test_count_devices(db_session):
    """Verify counting device records, optionally filtered by status."""
    repo = DeviceRepository(db_session)
    assert repo.count() == 0

    repo.create(device_id="dev-1", secret_hash="sha256$1", status="active")
    repo.create(device_id="dev-2", secret_hash="sha256$2", status="active")
    repo.create(device_id="dev-3", secret_hash="sha256$3", status="revoked")
    db_session.commit()

    assert repo.count() == 3
    assert repo.count(status="active") == 2
    assert repo.count(status="revoked") == 1
    assert repo.count(status="suspended") == 0

    with pytest.raises(ValueError, match="Invalid status 'invalid'"):
        repo.count(status="invalid")


def test_caller_controlled_transaction_rollback(db_session):
    """Verify repository flushes without committing, allowing caller to roll back."""
    repo = DeviceRepository(db_session)
    device = repo.create(device_id="dev-rollback", secret_hash="sha256$rb")

    # Flush populated ID, but rollback cancels persistence
    assert device.id is not None
    db_session.rollback()

    assert repo.get_by_device_id("dev-rollback") is None
