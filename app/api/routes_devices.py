"""
app/api/routes_devices.py — Physical access terminal (IoT device) registry routes.
Restricted to administrators. Never leaks secret_hash, tokens, or biometric data.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_current_admin
from app.db.session import get_db
from app.repositories.device_repository import DeviceRepository

router = APIRouter(tags=["Devices"])


class DeviceItem(BaseModel):
    device_id: str = Field(..., description="Unique physical hardware terminal identifier")
    name: Optional[str] = Field(None, description="Human-readable terminal name or physical installation location")
    status: str = Field(..., description="Lifecycle status (active, suspended, revoked)")
    key_version: int = Field(..., description="Active credential key version for rotation")


class DevicesResponse(BaseModel):
    devices: List[DeviceItem] = Field(..., description="List of registered physical access terminals")
    total: int = Field(..., description="Total count of registered terminals")
    active_count: int = Field(..., description="Count of currently active terminals")


@router.get("/devices", response_model=DevicesResponse)
def list_devices(
    admin: AuthenticatedUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    List registered hardware terminals and summary counts.
    Restricted strictly to administrators with verified non-revoked session.
    Data minimization: secret_hash is strictly excluded.
    """
    repo = DeviceRepository(db)
    try:
        devices = repo.list_devices()
        total = repo.count()
        active = repo.count(status="active")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Database failure while retrieving device registry.",
        ) from exc

    return {
        "devices": [
            DeviceItem(
                device_id=d.device_id,
                name=d.name,
                status=d.status,
                key_version=d.key_version,
            )
            for d in devices
        ],
        "total": total,
        "active_count": active,
    }
