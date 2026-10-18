"""
app/repositories/device_repository.py — Data access repository for DeviceRecord entities.
Encapsulates database operations for physical access terminals (IoT devices) using SQLAlchemy 2.0.
Decoupled from FastAPI HTTP routes and authentication logic.
Transaction boundaries are owned by the caller (session context manager / dependency).

Security Guarantees:
- Never stores, returns, logs, or exposes raw device secrets or HMAC signing keys.
- Operates exclusively with cryptographic verifiers / hashed credentials (secret_hash).
- Never includes biometric audio, embeddings, or Firebase tokens in records or logs.
"""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import DeviceRecord


class DeviceRepositoryError(Exception):
    """Base exception for device repository errors."""
    pass


class DuplicateDeviceError(DeviceRepositoryError, ValueError):
    """Raised when attempting to create a device with an existing device_id."""
    pass


class DeviceNotFoundError(DeviceRepositoryError, KeyError):
    """Raised when a requested device is not found."""
    pass


class DeviceRepository:
    """
    SQLAlchemy 2.0 repository managing persistence and queries for DeviceRecord.
    Methods operate within the caller's Session and perform flushes where needed,
    leaving transaction commit and rollback control to the caller.
    """

    VALID_STATUSES = frozenset({"active", "suspended", "revoked"})

    def __init__(self, session: Session):
        if session is None:
            raise ValueError("DeviceRepository requires an active SQLAlchemy Session.")
        self.session = session

    def create(
        self,
        device_id: str,
        secret_hash: str,
        name: Optional[str] = None,
        status: str = "active",
        key_version: int = 1,
        metadata_json: Optional[str] = None,
    ) -> DeviceRecord:
        """
        Create and persist a new DeviceRecord in the database.
        Flushes to the database transaction to verify constraints and populate autoincrement ID.
        Does NOT commit the transaction.
        """
        if not device_id or not device_id.strip():
            raise ValueError("device_id must be a non-empty string.")

        if not secret_hash or not secret_hash.strip():
            raise ValueError("secret_hash must be a non-empty string.")

        clean_device_id = device_id.strip()
        clean_secret_hash = secret_hash.strip()

        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(self.VALID_STATUSES)}.")

        if key_version < 1:
            raise ValueError("key_version must be at least 1.")

        now = datetime.now(timezone.utc)
        record = DeviceRecord(
            device_id=clean_device_id,
            name=name.strip() if name else None,
            status=status,
            secret_hash=clean_secret_hash,
            key_version=key_version,
            created_at=now,
            updated_at=now,
            metadata_json=metadata_json,
        )

        self.session.add(record)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise DuplicateDeviceError(
                f"Device with device_id '{clean_device_id}' already exists."
            ) from exc

        return record

    def get_by_device_id(self, device_id: str) -> Optional[DeviceRecord]:
        """
        Retrieve a device record by unique device_id string.
        Returns None if not found.
        """
        if not device_id:
            return None
        stmt = select(DeviceRecord).where(DeviceRecord.device_id == device_id.strip())
        return self.session.scalar(stmt)

    def get_by_id(self, record_id: int) -> Optional[DeviceRecord]:
        """
        Retrieve a device record by primary key integer ID.
        """
        return self.session.get(DeviceRecord, record_id)

    def get_or_raise(self, device_id: str) -> DeviceRecord:
        """
        Retrieve a device record by device_id, raising DeviceNotFoundError if not found.
        """
        record = self.get_by_device_id(device_id)
        if record is None:
            raise DeviceNotFoundError(f"Device '{device_id}' not found.")
        return record

    def list_devices(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[DeviceRecord]:
        """
        List devices ordered alphabetically by device_id.
        Optionally filters by lifecycle status and supports pagination.
        """
        stmt = select(DeviceRecord).order_by(DeviceRecord.device_id)
        if status is not None:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(self.VALID_STATUSES)}.")
            stmt = stmt.where(DeviceRecord.status == status)

        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)

        return list(self.session.scalars(stmt).all())

    def update(
        self,
        device_id: str,
        name: Optional[str] = None,
        status: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> Optional[DeviceRecord]:
        """
        Update permitted metadata and lifecycle fields of an existing device.
        Returns the updated record, or None if the device does not exist.
        Flushes changes to the session without committing.
        """
        record = self.get_by_device_id(device_id)
        if record is None:
            return None

        if name is not None:
            record.name = name.strip() if name else None

        if status is not None:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(self.VALID_STATUSES)}.")
            record.status = status

        if metadata_json is not None:
            record.metadata_json = metadata_json

        record.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return record

    def revoke(self, device_id: str) -> Optional[DeviceRecord]:
        """
        Revoke an active or suspended device.
        Transitions status to 'revoked' and updates timestamp.
        Returns the updated record, or None if not found.
        Flushes changes to the session without committing.
        """
        return self.update(device_id=device_id, status="revoked")

    def delete(self, device_id: str) -> bool:
        """
        Remove a device record from the database.
        Returns True if deleted, False if the device was not found.
        Flushes deletion to the session without committing.
        """
        record = self.get_by_device_id(device_id)
        if record is None:
            return False

        self.session.delete(record)
        self.session.flush()
        return True

    def count(self, status: Optional[str] = None) -> int:
        """
        Return total number of device records, optionally filtered by status.
        """
        stmt = select(func.count(DeviceRecord.id))
        if status is not None:
            if status not in self.VALID_STATUSES:
                raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(self.VALID_STATUSES)}.")
            stmt = stmt.where(DeviceRecord.status == status)
        return self.session.scalar(stmt) or 0
