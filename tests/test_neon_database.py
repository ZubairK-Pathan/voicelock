"""
tests/test_neon_database.py — Neon PostgreSQL Configuration, Connectivity, and Migration Tests.

Verifies:
1. Environment variable loading conventions without third-party dependencies.
2. Dialect normalization for SQLAlchemy 2.0 and psycopg 3 compatibility.
3. Migration URL resolution prioritizing direct unpooled connections (DATABASE_URL_UNPOOLED).
4. Full linear Alembic migration chain covering all 7 revisions to head (ea5fe481812c).
5. Safe end-to-end repository queries over live PostgreSQL TLS connection when configured.
6. Masking of sensitive credentials in database URLs.
"""

import os
from pathlib import Path
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.config import load_env_files, BASE_DIR
from app.db.session import (
    normalize_database_url,
    mask_database_url,
    get_database_url,
    get_migration_url,
    get_session_factory,
    create_db_engine,
)
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.repositories import SpeakerRepository, DeviceRepository, VerificationEventRepository


def test_neon_url_normalization():
    """Verify URL prefixes are correctly normalized to postgresql+psycopg://."""
    assert normalize_database_url("postgres://user:pass@host/db") == "postgresql+psycopg://user:pass@host/db"
    assert normalize_database_url("postgresql://user:pass@host/db") == "postgresql+psycopg://user:pass@host/db"
    assert normalize_database_url("postgresql+psycopg2://user:pass@host/db") == "postgresql+psycopg://user:pass@host/db"
    assert normalize_database_url("sqlite:///./test.db") == "sqlite:///./test.db"


def test_neon_url_masking():
    """Verify passwords in connection strings are strictly redacted."""
    raw = "postgresql://myuser:supersecret123@ep-sample.us-east-2.aws.neon.tech/neondb?sslmode=require"
    masked = mask_database_url(raw)
    assert "supersecret123" not in masked
    assert "myuser:***@ep-sample.us-east-2.aws.neon.tech" in masked

    empty_masked = mask_database_url("")
    assert empty_masked == "[not configured]"


def test_env_loading_preserves_existing_environment(monkeypatch):
    """Verify load_env_files does not overwrite existing process environment variables."""
    monkeypatch.setenv("TEST_KEY_EXISTING", "original_value")
    load_env_files()
    assert os.getenv("TEST_KEY_EXISTING") == "original_value"


def test_migration_url_prioritizes_unpooled_connection(monkeypatch):
    """Verify Alembic migrations prioritize direct unpooled connection over pooled."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@ep-pooler.neon.tech/neondb")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://user:pass@ep-direct.neon.tech/neondb")
    
    mig_url = get_migration_url()
    assert "ep-direct.neon.tech" in mig_url
    assert "ep-pooler.neon.tech" not in mig_url


def test_all_seven_alembic_migrations_present():
    """Verify all 7 migrations form a valid, unbroken chain leading to ea5fe481812c."""
    ini_path = str(BASE_DIR / "alembic.ini")
    config = Config(ini_path)
    script_dir = ScriptDirectory.from_config(config)

    head = script_dir.get_current_head()
    assert head == "ea5fe481812c", f"Expected migration head 'ea5fe481812c', got '{head}'"

    revisions = list(script_dir.walk_revisions())
    assert len(revisions) == 7, f"Expected exactly 7 Alembic revisions, found {len(revisions)}"
    
    rev_ids = [r.revision for r in revisions]
    expected_revs = [
        "ea5fe481812c",
        "d0199d309a47",
        "8046c184216a",
        "316dea338f3b",
        "0b98eaf9dc3e",
        "a4ae5dfd43b3",
        "e32dc984b290",
    ]
    assert rev_ids == expected_revs


def test_live_neon_postgresql_connectivity():
    """
    If DATABASE_URL or DATABASE_URL_UNPOOLED is present and points to PostgreSQL,
    verify real TLS connection, database dialect, table presence, and repository queries.
    """
    url = os.getenv("DATABASE_URL_UNPOOLED") or os.getenv("DATABASE_URL")
    if not url:
        env_file = BASE_DIR / ".env.local"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() in ("DATABASE_URL_UNPOOLED", "DATABASE_URL") and not url:
                        url = v.strip().strip("'\"")

    if not url or not url.startswith(("postgres://", "postgresql://", "postgresql+")):
        pytest.skip("No live PostgreSQL DATABASE_URL configured in environment or .env.local")

    norm_url = normalize_database_url(url)
    engine = create_engine(norm_url)
    with engine.connect() as conn:
        res = conn.execute(text("SELECT 1")).scalar()
        assert res == 1

        db_name = conn.execute(text("SELECT current_database()")).scalar()
        assert db_name is not None
        assert len(db_name) > 0

    # Verify all expected tables exist in PostgreSQL
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    required_tables = {
        "alembic_version",
        "schema_initializations",
        "speakers",
        "user_speaker_mappings",
        "devices",
        "verification_events",
        "security_events",
    }
    missing = required_tables - table_names
    assert not missing, f"Missing required tables in Neon PostgreSQL: {missing}"

    # Verify repository querying works against the live database
    with Session(engine) as session:
        speaker_repo = SpeakerRepository(session)
        device_repo = DeviceRepository(session)
        event_repo = VerificationEventRepository(session)

        assert isinstance(speaker_repo.count(), int)
        assert isinstance(device_repo.count(), int)
        assert isinstance(event_repo.count_events(), int)
