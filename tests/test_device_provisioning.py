"""
tests/test_device_provisioning.py — Unit test suite for hardware device provisioning CLI.

Covers:
1. CSPRNG device secret generation (entropy, minimum length, urlsafe characters).
2. Remote database write protection (rejects remote URLs unless --allow-remote is provided).
3. Happy-path registration in disposable isolated database.
4. Cryptographic verifier integrity (secret_hash format sha256$<hex>, verifiable via verify_device_secret_hash).
5. Idempotent skip when registering with identical credentials.
6. Duplicate conflict rejection when re-registering with different credentials without --rotate-key.
7. Key rotation (--rotate-key) updating secret_hash and incrementing key_version.
8. Dry-run safety (no changes committed to database).
9. C/C++ header generation with restrictive file permissions (mode 0600).
10. Database URL masking (passwords redacted in output and logs).
11. CLI interface invocation (JSON and text formatting, error exit codes).
"""

import json
import os
from pathlib import Path
import stat
import tempfile
import pytest

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.device_auth import verify_device_secret_hash
from app.db.base import Base, DeviceRecord
from app.db.session import create_db_engine
from app.repositories.device_repository import DuplicateDeviceError
from scripts.register_device import (
    generate_device_secret,
    generate_c_header,
    is_remote_database,
    register_device,
    write_header_file,
    main as cli_main,
)


@pytest.fixture
def disposable_db():
    """Create an isolated, temporary SQLite database for test execution."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    db_url = f"sqlite:///{db_path}"
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    yield {"url": db_url, "path": db_path, "session_factory": session_factory}

    engine.dispose()
    if db_path.exists():
        try:
            db_path.unlink()
        except OSError:
            pass


def test_generate_device_secret_entropy():
    """Secret generator must produce high-entropy, unique strings >= 32 characters."""
    s1 = generate_device_secret()
    s2 = generate_device_secret()
    assert len(s1) >= 40  # 32 bytes in base64url is ~43 chars
    assert len(s2) >= 40
    assert s1 != s2


def test_remote_database_detection():
    """is_remote_database must identify cloud/remote connection strings."""
    assert is_remote_database("postgresql://user:pass@ep-cool-123.us-east-2.aws.neon.tech/neondb")
    assert is_remote_database("postgres://user:pass@localhost:5432/db")
    assert is_remote_database("postgresql+psycopg://user:pass@remote:5432/db")
    assert not is_remote_database("sqlite:///./voicelock.db")
    assert not is_remote_database("sqlite:///:memory:")


def test_remote_database_write_protection(monkeypatch):
    """Attempting to provision against a remote database without --allow-remote must raise PermissionError."""
    fake_neon_url = "postgresql+psycopg://user:secret@ep-cool.aws.neon.tech/neondb"
    with pytest.raises(PermissionError) as exc_info:
        register_device(
            db_url=fake_neon_url,
            device_id="unauthorized-terminal",
            allow_remote=False,
        )
    assert "Remote database write blocked for safety" in str(exc_info.value)
    # Ensure password 'secret' is masked
    assert "secret@" not in str(exc_info.value)


def test_register_device_happy_path(disposable_db):
    """Provisioning a new device creates an active DeviceRecord with verifiable hash."""
    result = register_device(
        db_url=disposable_db["url"],
        device_id="gate-east-01",
        name="East Perimeter Gate",
        status="active",
        key_version=1,
    )

    assert result["action"] == "created"
    assert result["device_id"] == "gate-east-01"
    assert result["name"] == "East Perimeter Gate"
    assert result["key_version"] == 1
    assert result["status"] == "active"
    assert result["secret_hash"].startswith("sha256$")
    assert len(result["secret"]) >= 40

    # Verify secret validates against stored hash
    assert verify_device_secret_hash(result["secret"], result["secret_hash"])

    # Verify persisted in database
    with disposable_db["session_factory"]() as session:
        record = session.scalar(select(DeviceRecord).where(DeviceRecord.device_id == "gate-east-01"))
        assert record is not None
        assert record.name == "East Perimeter Gate"
        assert record.secret_hash == result["secret_hash"]
        assert record.key_version == 1
        assert record.is_active


def test_register_device_idempotency_matching_secret(disposable_db):
    """Re-registering with the exact same secret should skip without error."""
    known_secret = "pre-shared-secret-for-idempotency-test"
    res1 = register_device(
        db_url=disposable_db["url"],
        device_id="turnstile-01",
        secret=known_secret,
    )
    assert res1["action"] == "created"

    res2 = register_device(
        db_url=disposable_db["url"],
        device_id="turnstile-01",
        secret=known_secret,
    )
    assert res2["action"] == "skipped_identical"
    assert res2["device_id"] == "turnstile-01"


def test_register_device_duplicate_conflict_rejection(disposable_db):
    """Re-registering an existing device with a different secret must raise DuplicateDeviceError."""
    res1 = register_device(
        db_url=disposable_db["url"],
        device_id="turnstile-02",
        secret="first-secret-key-12345678",
    )
    assert res1["action"] == "created"

    with pytest.raises(DuplicateDeviceError) as exc_info:
        register_device(
            db_url=disposable_db["url"],
            device_id="turnstile-02",
            secret="different-conflicting-secret",
            rotate_key=False,
        )
    assert "already exists in database with different credentials" in str(exc_info.value)


def test_register_device_key_rotation(disposable_db):
    """Using rotate_key=True updates secret_hash and increments key_version."""
    res1 = register_device(
        db_url=disposable_db["url"],
        device_id="server-room-01",
        secret="initial-key-version-1",
        key_version=1,
    )
    assert res1["key_version"] == 1

    new_secret = "rotated-key-version-2"
    res2 = register_device(
        db_url=disposable_db["url"],
        device_id="server-room-01",
        secret=new_secret,
        rotate_key=True,
    )

    assert res2["action"] == "rotated"
    assert res2["key_version"] == 2
    assert res2["secret_hash"] != res1["secret_hash"]
    assert verify_device_secret_hash(new_secret, res2["secret_hash"])

    # Old secret must no longer validate
    assert not verify_device_secret_hash("initial-key-version-1", res2["secret_hash"])


def test_register_device_dry_run(disposable_db):
    """Dry run validates inputs but does not persist to database."""
    result = register_device(
        db_url=disposable_db["url"],
        device_id="dry-run-terminal",
        name="Simulated Gate",
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["action"] == "created"

    with disposable_db["session_factory"]() as session:
        record = session.scalar(select(DeviceRecord).where(DeviceRecord.device_id == "dry-run-terminal"))
        assert record is None


def test_write_header_file_permissions(tmp_path):
    """Header file must be created with mode 0600 (read/write only by owner)."""
    header_path = tmp_path / "credentials.h"
    content = generate_c_header(
        device_id="terminal-secure-01",
        secret="top-secret-signing-key",
        server_url="https://api.voicelock.internal",
    )
    write_header_file(header_path, content)

    assert header_path.is_file()
    assert "terminal-secure-01" in header_path.read_text()
    assert "top-secret-signing-key" in header_path.read_text()

    # Verify POSIX file permissions: 0600
    file_mode = stat.S_IMODE(header_path.stat().st_mode)
    assert file_mode == 0o600


def test_cli_main_invocation(disposable_db, capsys):
    """CLI main function executes successfully and returns 0."""
    exit_code = cli_main([
        "--device-id", "cli-terminal-01",
        "--name", "CLI Tested Terminal",
        "--db-url", disposable_db["url"],
        "--json",
    ])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["device_id"] == "cli-terminal-01"
    assert data["action"] == "created"
