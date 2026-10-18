"""
app/core/database.py — Re-export database utilities for core module integration.
"""

from app.db import (
    Base,
    SchemaInitialization,
    SpeakerRecord,
    UserSpeakerMapping,
    DeviceRecord,
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

__all__ = [
    "Base",
    "SchemaInitialization",
    "SpeakerRecord",
    "UserSpeakerMapping",
    "DeviceRecord",
    "get_database_url",
    "normalize_database_url",
    "mask_database_url",
    "create_db_engine",
    "get_engine",
    "get_session_factory",
    "reset_engine",
    "get_db",
    "get_db_context",
]
