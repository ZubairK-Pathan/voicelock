"""
tests/test_database.py — Milestone 3C.1 Database Foundation and Alembic Migration Test Suite.

Verifies:
1. Database URL resolution, dialect normalization (postgres -> postgresql+psycopg), and production fail-closed semantics.
2. Sensitive credential masking (mask_database_url) preventing secret leakage in logs.
3. Connection pooling configuration for SQLite and PostgreSQL engines.
4. Lazy engine/session initialization ensuring imports do not trigger database connections.
5. Session context manager and FastAPI dependency lifecycle (commit, rollback, close).
6. Alembic migration execution (upgrade to head, downgrade to base) against a disposable test database.
7. Existing application startup and imports remain completely independent of live database infrastructure.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool, QueuePool

from alembic.config import Config
from alembic import command

from app.db.base import Base, SchemaInitialization, SpeakerRecord, UserSpeakerMapping, DeviceRecord
from app.db.session import (
    get_database_url,
    normalize_database_url,
    mask_database_url,
    create_db_engine,
    get_engine,
    get_session_factory,
    reset_engine,
    get_db,
    get_db_context,
)


@pytest.fixture(autouse=True)
def cleanup_engine_state():
    """Ensure engine singletons are disposed between test runs."""
    reset_engine()
    yield
    reset_engine()


# ─── 1. Configuration & Normalization Tests ────────────────────────────────────

def test_database_url_dialect_normalization():
    """Verify postgresql dialect prefix normalization for SQLAlchemy 2.0 / psycopg3."""
    assert normalize_database_url("postgres://usr:pwd@host/db") == "postgresql+psycopg://usr:pwd@host/db"
    assert normalize_database_url("postgresql://usr:pwd@host/db") == "postgresql+psycopg://usr:pwd@host/db"
    assert normalize_database_url("postgresql+psycopg2://usr:pwd@host/db") == "postgresql+psycopg://usr:pwd@host/db"
    assert normalize_database_url("postgresql+psycopg://usr:pwd@host/db") == "postgresql+psycopg://usr:pwd@host/db"
    assert normalize_database_url("sqlite:///./test.db") == "sqlite:///./test.db"


def test_database_url_resolution_defaults():
    """In development/testing, missing DATABASE_URL falls back to local SQLite."""
    with patch.dict(os.environ, {"DATABASE_URL": "", "VOICELOCK_ENV": "development"}):
        url = get_database_url()
        assert url.startswith("sqlite:///")


def test_database_url_production_fail_closed():
    """In production, missing DATABASE_URL raises RuntimeError."""
    with patch.dict(os.environ, {"DATABASE_URL": "", "VOICELOCK_ENV": "production"}):
        with pytest.raises(RuntimeError) as exc_info:
            get_database_url()
        assert "must be explicitly configured in production" in str(exc_info.value)


# ─── 2. Credential Masking Safety Tests ────────────────────────────────────────

def test_mask_database_url_redacts_password():
    """Verify password is redacted with asterisks in standard database URLs."""
    raw = "postgresql+psycopg://app_user:SuperSecretPassword123@db.example.internal:5432/voicelock_prod"
    masked = mask_database_url(raw)
    assert "SuperSecretPassword123" not in masked
    assert "app_user:***@db.example.internal:5432/voicelock_prod" in masked


def test_mask_database_url_handles_sqlite_and_empty():
    """SQLite URLs and empty strings are handled safely without failure."""
    assert mask_database_url("sqlite:///./voicelock.db") == "sqlite:///./voicelock.db"
    assert mask_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
    assert mask_database_url("") == "[not configured]"
    assert mask_database_url(None) == "[not configured]"


# ─── 3. Engine Creation & Connection Pooling Tests ─────────────────────────────

def test_sqlite_in_memory_engine_uses_static_pool():
    """SQLite in-memory databases must use StaticPool to preserve state across connections."""
    engine = create_db_engine("sqlite:///:memory:")
    assert isinstance(engine.pool, StaticPool)


def test_postgresql_engine_pool_configuration():
    """PostgreSQL engines must configure QueuePool with configurable parameters."""
    test_env = {
        "DB_POOL_SIZE": "8",
        "DB_MAX_OVERFLOW": "15",
        "DB_POOL_TIMEOUT": "20.0",
        "DB_POOL_RECYCLE": "900",
    }
    with patch.dict(os.environ, test_env):
        engine = create_db_engine("postgresql+psycopg://user:pwd@localhost:5432/db")
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 8
        assert engine.pool._max_overflow == 15
        assert engine.pool._timeout == 20.0
        assert engine.pool._recycle == 900


def test_lazy_engine_initialization_prevents_premature_connection():
    """Resetting engine leaves _engine as None until explicitly requested."""
    reset_engine()
    from app.db import session as db_session
    assert db_session._engine is None
    # Engine is created only when get_engine() is called
    engine = get_engine("sqlite:///:memory:")
    assert engine is not None
    assert db_session._engine is not None


# ─── 4. Session Context Manager & Dependency Tests ─────────────────────────────

def test_db_context_commit_and_query_lifecycle():
    """Verify get_db_context commits successful transactions and cleans up."""
    test_db_url = "sqlite:///:memory:"
    engine = get_engine(test_db_url)
    Base.metadata.create_all(engine)

    # Insert record using context manager
    with get_db_context(test_db_url) as db:
        init_entry = SchemaInitialization(
            component="database_foundation",
            description="Milestone 3C.1 initial schema verification",
        )
        db.add(init_entry)

    # Query back in a new session to confirm commit
    with get_db_context(test_db_url) as db:
        result = db.scalar(select(SchemaInitialization).where(SchemaInitialization.component == "database_foundation"))
        assert result is not None
        assert result.component == "database_foundation"
        assert result.description == "Milestone 3C.1 initial schema verification"


def test_db_context_rollback_on_exception():
    """Verify get_db_context rolls back on unhandled exceptions."""
    test_db_url = "sqlite:///:memory:"
    engine = get_engine(test_db_url)
    Base.metadata.create_all(engine)

    with pytest.raises(ValueError):
        with get_db_context(test_db_url) as db:
            db.add(SchemaInitialization(component="failed_entry"))
            raise ValueError("Simulated transaction failure")

    with get_db_context(test_db_url) as db:
        result = db.scalar(select(SchemaInitialization).where(SchemaInitialization.component == "failed_entry"))
        assert result is None


def test_fastapi_get_db_dependency_lifecycle():
    """Verify get_db dependency yields active session and closes it."""
    test_db_url = "sqlite:///:memory:"
    get_engine(test_db_url)

    gen = get_db()
    session = next(gen)
    assert session.is_active is True
    # Complete generator to trigger finally block
    with pytest.raises(StopIteration):
        next(gen)


# ─── 5. Alembic Migration Upgrade & Downgrade Lifecycle ────────────────────────

def test_alembic_upgrade_and_downgrade_disposable_sqlite_db():
    """
    Execute real Alembic migration against a disposable SQLite database file:
    1. Runs alembic upgrade head -> creates schema_initializations table.
    2. Verifies schema creation and executes insert/select.
    3. Runs alembic downgrade base -> drops schema_initializations table.
    4. Verifies clean schema teardown.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    disposable_url = f"sqlite:///{tmp_db_path}"
    project_root = Path(__file__).resolve().parent.parent
    alembic_ini_path = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", disposable_url)

    try:
        # Step 1: Upgrade to head
        command.upgrade(alembic_cfg, "head")

        engine = create_db_engine(disposable_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "schema_initializations" in tables
        assert "speakers" in tables
        assert "user_speaker_mappings" in tables
        assert "alembic_version" in tables

        # Step 2: Verify table operations
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO schema_initializations (component, initialized_at, description) VALUES (:comp, datetime('now'), :desc)"),
                {"comp": "test_alembic_mig", "desc": "Alembic verification record"},
            )
            conn.commit()
            row = conn.execute(text("SELECT component, description FROM schema_initializations")).fetchone()
            assert row[0] == "test_alembic_mig"
            assert row[1] == "Alembic verification record"
        engine.dispose()

        # Step 3: Downgrade back to base
        command.downgrade(alembic_cfg, "base")

        engine_post = create_db_engine(disposable_url)
        inspector_post = inspect(engine_post)
        tables_post = inspector_post.get_table_names()
        assert "schema_initializations" not in tables_post
        assert "speakers" not in tables_post
        assert "user_speaker_mappings" not in tables_post
        engine_post.dispose()

    finally:
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def test_speakers_schema_migration_and_constraints(monkeypatch):
    """
    Verify speakers table creation, constraints, ORM mappings, and single-revision rollback.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    disposable_url = f"sqlite:///{tmp_db_path}"
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    reset_engine()

    project_root = Path(__file__).resolve().parent.parent
    alembic_ini_path = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", disposable_url)

    try:
        # 1. Migrate to head
        command.upgrade(alembic_cfg, "head")

        # 2. Insert valid SpeakerRecord via ORM session
        with get_db_context() as session:
            speaker = SpeakerRecord(
                speaker_id="Zubair",
                full_name="Zubair K. Pathan",
                status="active",
                embedding_dim=192,
                sample_count=3,
                metadata_json='{"device": "macbook_pro_m2"}',
            )
            session.add(speaker)

        # 3. Query back and verify ORM fields
        with get_db_context() as session:
            record = session.scalar(select(SpeakerRecord).where(SpeakerRecord.speaker_id == "Zubair"))
            assert record is not None
            assert record.speaker_id == "Zubair"
            assert record.full_name == "Zubair K. Pathan"
            assert record.status == "active"
            assert record.is_active is True
            assert record.embedding_dim == 192
            assert record.sample_count == 3
            assert record.created_at is not None
            assert record.updated_at is not None

        # 4. Verify unique constraint on speaker_id
        with pytest.raises(IntegrityError):
            with get_db_context() as session:
                duplicate_speaker = SpeakerRecord(
                    speaker_id="Zubair",
                    full_name="Duplicate Name",
                )
                session.add(duplicate_speaker)

        reset_engine()

        # 5. Rollback only the speakers migration (a4ae5dfd43b3 -> e32dc984b290)
        command.downgrade(alembic_cfg, "e32dc984b290")

        engine = create_db_engine(disposable_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "speakers" not in tables
        assert "schema_initializations" in tables
        engine.dispose()

        # 6. Re-apply upgrade to head
        command.upgrade(alembic_cfg, "head")
        engine_reup = create_db_engine(disposable_url)
        tables_reup = inspect(engine_reup).get_table_names()
        assert "speakers" in tables_reup
        engine_reup.dispose()

    finally:
        reset_engine()
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def test_user_speaker_mappings_schema_migration_and_constraints(monkeypatch):
    """
    Verify user_speaker_mappings table creation, foreign keys, unique constraints (1-to-1),
    ORM mappings, and single-revision migration rollback.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    disposable_url = f"sqlite:///{tmp_db_path}"
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    reset_engine()

    project_root = Path(__file__).resolve().parent.parent
    alembic_ini_path = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", disposable_url)

    try:
        # 1. Migrate to head (runs initial, speakers, and user_speaker_mappings migrations)
        command.upgrade(alembic_cfg, "head")

        engine = create_db_engine(disposable_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "user_speaker_mappings" in tables
        assert "speakers" in tables

        # Verify foreign keys and indexes via inspector
        fks = inspector.get_foreign_keys("user_speaker_mappings")
        assert len(fks) >= 1
        assert fks[0]["referred_table"] == "speakers"
        assert fks[0]["referred_columns"] == ["speaker_id"]

        indexes = {idx["name"]: idx for idx in inspector.get_indexes("user_speaker_mappings")}
        assert "ix_user_speaker_mappings_firebase_uid" in indexes
        assert indexes["ix_user_speaker_mappings_firebase_uid"]["unique"] == 1
        assert "ix_user_speaker_mappings_speaker_id" in indexes
        assert indexes["ix_user_speaker_mappings_speaker_id"]["unique"] == 1
        engine.dispose()

        # 2. Insert valid SpeakerRecord and UserSpeakerMapping via ORM session
        with get_db_context() as session:
            speaker = SpeakerRecord(
                speaker_id="Zubair",
                full_name="Zubair K. Pathan",
                status="active",
                embedding_dim=192,
                sample_count=3,
            )
            session.add(speaker)
            mapping = UserSpeakerMapping(
                firebase_uid="firebase_uid_zubair_test_123",
                speaker_id="Zubair",
                assigned_by="admin_bootstrap",
                metadata_json='{"provisioned_at": "test_suite"}',
            )
            session.add(mapping)

        # 3. Query back and verify ORM fields and relationships
        with get_db_context() as session:
            record = session.scalar(
                select(UserSpeakerMapping).where(
                    UserSpeakerMapping.firebase_uid == "firebase_uid_zubair_test_123"
                )
            )
            assert record is not None
            assert record.firebase_uid == "firebase_uid_zubair_test_123"
            assert record.speaker_id == "Zubair"
            assert record.assigned_by == "admin_bootstrap"
            assert record.metadata_json == '{"provisioned_at": "test_suite"}'
            assert record.created_at is not None
            assert record.updated_at is not None
            # Test ORM relationship traversal
            assert record.speaker is not None
            assert record.speaker.speaker_id == "Zubair"
            assert record.speaker.full_name == "Zubair K. Pathan"

        # 4. Enforce 1-to-1 cardinality: Duplicate firebase_uid must be rejected
        with get_db_context() as session:
            speaker2 = SpeakerRecord(speaker_id="Advait", full_name="Advait Patel")
            session.add(speaker2)

        with pytest.raises(IntegrityError):
            with get_db_context() as session:
                duplicate_user = UserSpeakerMapping(
                    firebase_uid="firebase_uid_zubair_test_123",  # Same user
                    speaker_id="Advait",                           # Different speaker
                )
                session.add(duplicate_user)

        # 5. Enforce 1-to-1 cardinality: Duplicate speaker_id must be rejected
        with pytest.raises(IntegrityError):
            with get_db_context() as session:
                duplicate_speaker = UserSpeakerMapping(
                    firebase_uid="firebase_uid_new_user_456",     # Different user
                    speaker_id="Zubair",                          # Already mapped speaker
                )
                session.add(duplicate_speaker)

        reset_engine()

        # 6. Single-revision rollback (0b98eaf9dc3e -> a4ae5dfd43b3)
        command.downgrade(alembic_cfg, "a4ae5dfd43b3")

        engine = create_db_engine(disposable_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "user_speaker_mappings" not in tables
        assert "speakers" in tables
        assert "schema_initializations" in tables
        engine.dispose()

        # 7. Re-apply upgrade to head
        command.upgrade(alembic_cfg, "head")
        engine_reup = create_db_engine(disposable_url)
        tables_reup = inspect(engine_reup).get_table_names()
        assert "user_speaker_mappings" in tables_reup
        engine_reup.dispose()

    finally:
        reset_engine()
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


def test_devices_schema_migration_and_constraints(monkeypatch):
    """
    Verify devices table creation, columns, unique constraints on device_id,
    ORM mappings, lifecycle status, and single-revision migration rollback.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    disposable_url = f"sqlite:///{tmp_db_path}"
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    reset_engine()

    project_root = Path(__file__).resolve().parent.parent
    alembic_ini_path = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", disposable_url)

    try:
        # 1. Migrate to head (runs all migrations including create_devices_table)
        command.upgrade(alembic_cfg, "head")

        engine = create_db_engine(disposable_url)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "devices" in tables
        assert "user_speaker_mappings" in tables
        assert "speakers" in tables
        assert "schema_initializations" in tables

        # Verify columns and indexes via inspector
        columns = {col["name"]: col for col in inspector.get_columns("devices")}
        assert "id" in columns
        assert "device_id" in columns
        assert "name" in columns
        assert "status" in columns
        assert "secret_hash" in columns
        assert "key_version" in columns
        assert "created_at" in columns
        assert "updated_at" in columns
        assert "metadata_json" in columns

        indexes = {idx["name"]: idx for idx in inspector.get_indexes("devices")}
        assert "ix_devices_device_id" in indexes
        assert indexes["ix_devices_device_id"]["unique"] == 1
        engine.dispose()

        # 2. Insert valid DeviceRecord via ORM session
        with get_db_context() as session:
            device = DeviceRecord(
                device_id="esp32-door-portal-01",
                name="Main Entrance Gate",
                status="active",
                secret_hash="sha256$mocked_credential_hash_value",
                key_version=1,
                metadata_json='{"location": "North Wing", "mac": "AA:BB:CC:DD:EE:FF"}',
            )
            session.add(device)

        # 3. Query back and verify ORM fields, timestamps, and is_active property
        with get_db_context() as session:
            record = session.scalar(
                select(DeviceRecord).where(
                    DeviceRecord.device_id == "esp32-door-portal-01"
                )
            )
            assert record is not None
            assert record.device_id == "esp32-door-portal-01"
            assert record.name == "Main Entrance Gate"
            assert record.status == "active"
            assert record.is_active is True
            assert record.secret_hash == "sha256$mocked_credential_hash_value"
            assert record.key_version == 1
            assert record.metadata_json == '{"location": "North Wing", "mac": "AA:BB:CC:DD:EE:FF"}'
            assert record.created_at is not None
            assert record.updated_at is not None

            # Test lifecycle status update to revoked
            record.status = "revoked"
            session.flush()
            assert record.is_active is False

        # 4. Enforce uniqueness: duplicate device_id must be rejected
        with pytest.raises(IntegrityError):
            with get_db_context() as session:
                duplicate_device = DeviceRecord(
                    device_id="esp32-door-portal-01",
                    name="Duplicate Device",
                    secret_hash="sha256$other_secret_hash",
                )
                session.add(duplicate_device)

        reset_engine()

        # 5. Single-revision rollback (316dea338f3b -> 0b98eaf9dc3e)
        command.downgrade(alembic_cfg, "0b98eaf9dc3e")

        engine_rb = create_db_engine(disposable_url)
        inspector_rb = inspect(engine_rb)
        tables_rb = inspector_rb.get_table_names()
        assert "devices" not in tables_rb
        assert "user_speaker_mappings" in tables_rb
        assert "speakers" in tables_rb
        assert "schema_initializations" in tables_rb
        engine_rb.dispose()

        # 6. Re-apply upgrade to head
        command.upgrade(alembic_cfg, "head")
        engine_reup = create_db_engine(disposable_url)
        tables_reup = inspect(engine_reup).get_table_names()
        assert "devices" in tables_reup
        engine_reup.dispose()

    finally:
        reset_engine()

def test_speakers_embedding_schema_migration(monkeypatch):
    """
    Verify migration 8046c184216a adds embedding_json to speakers table,
    supports ORM insert/query, and single-revision rollback (8046c184216a -> 316dea338f3b)
    cleanly drops embedding_json.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        tmp_db_path = Path(tmp_file.name)

    disposable_url = f"sqlite:///{tmp_db_path}"
    monkeypatch.setenv("DATABASE_URL", disposable_url)
    reset_engine()

    project_root = Path(__file__).resolve().parent.parent
    alembic_ini_path = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", disposable_url)

    try:
        # 1. Upgrade to head (includes 8046c184216a)
        command.upgrade(alembic_cfg, "head")

        engine = create_db_engine(disposable_url)
        inspector = inspect(engine)
        columns = [col["name"] for col in inspector.get_columns("speakers")]
        assert "embedding_json" in columns
        engine.dispose()

        # 2. Insert SpeakerRecord with embedding_json and query back
        test_json = '[-0.123, 0.456]'
        with get_db_context() as session:
            speaker = SpeakerRecord(
                speaker_id="ZubairEmbedding",
                full_name="Zubair With Vector",
                status="active",
                embedding_dim=192,
                embedding_json=test_json,
            )
            session.add(speaker)

        with get_db_context() as session:
            loaded = session.scalar(select(SpeakerRecord).where(SpeakerRecord.speaker_id == "ZubairEmbedding"))
            assert loaded is not None
            assert loaded.embedding_json == test_json

        reset_engine()

        # 3. Rollback single revision (8046c184216a -> 316dea338f3b)
        command.downgrade(alembic_cfg, "316dea338f3b")

        engine_rb = create_db_engine(disposable_url)
        inspector_rb = inspect(engine_rb)
        columns_rb = [col["name"] for col in inspector_rb.get_columns("speakers")]
        assert "embedding_json" not in columns_rb
        # Core columns still preserved
        assert "speaker_id" in columns_rb
        engine_rb.dispose()

        # 4. Re-apply upgrade to head
        command.upgrade(alembic_cfg, "head")
        engine_reup = create_db_engine(disposable_url)
        columns_reup = [col["name"] for col in inspect(engine_reup).get_columns("speakers")]
        assert "embedding_json" in columns_reup
        engine_reup.dispose()

    finally:
        reset_engine()
        if tmp_db_path.exists():
            try:
                tmp_db_path.unlink()
            except OSError:
                pass


# ─── 6. Application Startup & Import Decoupling ────────────────────────────────

def test_application_startup_without_live_database():
    """
    Verify application modules and FastAPI app can be imported and initialized
    without connecting to a live database or raising errors.
    """
    reset_engine()
    # Import app.main and cloud_api
    import app.main as app_main
    import cloud_api as legacy_api

    assert app_main.app is not None
    assert legacy_api.app is not None
