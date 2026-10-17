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
from sqlalchemy.pool import StaticPool, QueuePool

from alembic.config import Config
from alembic import command

from app.db.base import Base, SchemaInitialization
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
        engine_post.dispose()

    finally:
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
