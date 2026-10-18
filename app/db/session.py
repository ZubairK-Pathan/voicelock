"""
app/db/session.py — Centralized database configuration, connection pooling, and session management.

Key Guarantees:
1. Lazy Initialization: Engine and sessionmaker are instantiated only upon explicit invocation,
   ensuring importing the module never attempts an active database connection.
2. Production Fail-Closed: Missing DATABASE_URL in production raises RuntimeError.
3. Credential Safety: mask_database_url() redacts passwords from connection strings for safe logging.
4. Connection Pooling: Production PostgreSQL utilizes bounded QueuePool with keepalive pre-ping.
"""

from contextlib import contextmanager
import os
import threading
from typing import Generator, Optional
import urllib.parse

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, StaticPool, NullPool

from app.core.config import VOICELOCK_ENV


_engine_lock = threading.RLock()
_engine: Optional[Engine] = None
_engine_url: Optional[str] = None
_session_factory: Optional[sessionmaker[Session]] = None


def normalize_database_url(url: str) -> str:
    """
    Normalize dialect prefixes for SQLAlchemy 2.0 compatibility:
    - postgres:// -> postgresql+psycopg://
    - postgresql:// -> postgresql+psycopg://
    - postgresql+psycopg2:// -> postgresql+psycopg://
    """
    clean_url = url.strip()
    if clean_url.startswith("postgres://"):
        return "postgresql+psycopg://" + clean_url[len("postgres://"):]
    if clean_url.startswith("postgresql://") and not clean_url.startswith("postgresql+"):
        return "postgresql+psycopg://" + clean_url[len("postgresql://"):]
    if clean_url.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + clean_url[len("postgresql+psycopg2://"):]
    return clean_url


def mask_database_url(url: Optional[str]) -> str:
    """
    Sanitize database connection strings by redacting passwords.
    Example: postgresql+psycopg://user:password@localhost:5432/db -> postgresql+psycopg://user:***@localhost:5432/db
    """
    if not url or not url.strip():
        return "[not configured]"
    clean_url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(clean_url)
        if not parsed.password:
            return clean_url
        user_info = parsed.username or ""
        host_info = parsed.hostname or ""
        if parsed.port:
            host_info = f"{host_info}:{parsed.port}"
        netloc = f"{user_info}:***@{host_info}"
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "[sanitized-database-url]"


def get_database_url() -> str:
    """
    Resolve DATABASE_URL from environment variables.
    In development/testing: falls back to local SQLite 'sqlite:///./voicelock.db'.
    In production: strictly raises RuntimeError if DATABASE_URL is unset.
    """
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if raw_url:
        return normalize_database_url(raw_url)

    current_env = os.getenv("VOICELOCK_ENV", VOICELOCK_ENV).strip().lower()
    if current_env == "production":
        raise RuntimeError("DATABASE_URL must be explicitly configured in production environment.")

    # Safe default for local development / testing
    return "sqlite:///./voicelock.db"


def get_migration_url() -> str:
    """
    Resolve database URL for schema migrations.
    Prioritizes direct unpooled connection (DATABASE_URL_UNPOOLED) over pooled connection
    to prevent PgBouncer transaction-mode state, prepared statement leaks, and catalog lock issues.
    Falls back to get_database_url().
    """
    unpooled = os.getenv("DATABASE_URL_UNPOOLED", "").strip()
    if unpooled:
        return normalize_database_url(unpooled)
    return get_database_url()


def create_db_engine(database_url: Optional[str] = None) -> Engine:
    """
    Create a configured SQLAlchemy 2.0 engine with connection pooling.
    """
    url = database_url or get_database_url()
    echo = os.getenv("DB_ECHO", "false").lower() in ("true", "1")

    if url.startswith("sqlite"):
        is_memory = ":memory:" in url or "mode=memory" in url
        connect_args = {"check_same_thread": False}
        if is_memory:
            return create_engine(url, connect_args=connect_args, poolclass=StaticPool, echo=echo)
        return create_engine(url, connect_args=connect_args, echo=echo)

    # PostgreSQL / Other RDBMS connection pooling configuration
    pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
    max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    pool_timeout = float(os.getenv("DB_POOL_TIMEOUT", "30.0"))
    pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    return create_engine(
        url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        echo=echo,
    )


def get_engine(database_url: Optional[str] = None) -> Engine:
    """
    Return lazily initialized global engine singleton.
    If database_url is provided and differs from active engine, creates/reconfigures the engine.
    """
    global _engine, _engine_url
    target_url = normalize_database_url(database_url) if database_url else get_database_url()
    with _engine_lock:
        if _engine is None or _engine_url != target_url:
            if _engine is not None:
                _engine.dispose()
            _engine = create_db_engine(target_url)
            _engine_url = target_url
        return _engine


def get_session_factory(database_url: Optional[str] = None) -> sessionmaker[Session]:
    """
    Return lazily initialized sessionmaker bound to the active engine.
    """
    global _session_factory
    engine = get_engine(database_url)
    with _engine_lock:
        if _session_factory is None or _session_factory.kw.get("bind") != engine:
            _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return _session_factory


def reset_engine() -> None:
    """
    Dispose active engine connections and reset global singletons (primarily for unit tests).
    """
    global _engine, _session_factory, _engine_url
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
            _engine = None
        _session_factory = None
        _engine_url = None


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency: Yield a managed SQLAlchemy database session.
    Automatically closes session on request completion.
    """
    session_factory = get_session_factory()
    db: Session = session_factory()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context(database_url: Optional[str] = None) -> Generator[Session, None, None]:
    """
    Context manager for CLI scripts, migrations, and test harness execution:
    with get_db_context() as db:
        db.execute(...)
    """
    session_factory = get_session_factory(database_url)
    db: Session = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
