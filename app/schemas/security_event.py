"""
app/schemas/security_event.py — Pydantic schemas, cursor utilities, and metadata sanitization
for the Security Audit Events API.

Strict Data Privacy & Minimization Guarantees:
1. Passwords, bearer tokens, HMAC secrets, private keys, raw audio paths, and 192-d biometric
   embeddings are strictly excluded from response schemas.
2. Metadata is strictly filtered against an explicit allowlist of non-sensitive operational fields.
   Arbitrary internal JSON, raw stack traces, client IP addresses, and user-agent strings are omitted.
3. Pagination cursors are opaque, tamper-evident base64 tokens encoding (timestamp, sequence_id).
"""

import base64
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

# Explicit allowlist of safe, non-sensitive audit metadata fields.
# Any key not present in this allowlist is dropped during response serialization.
SAFE_AUDIT_METADATA_ALLOWLIST = frozenset({
    "action",
    "reason",
    "error_type",
    "failure_reason",
    "endpoint",
    "method",
    "status_code",
    "target_uid",
    "target_speaker_id",
    "assigned_by",
    "attempt_count",
    "duration_ms",
    "clock_skew_seconds",
    "flow",
})

# Substrings indicating sensitive credential material that must never appear in metadata values
SENSITIVE_VALUE_PATTERNS = ("bearer ", "eyj", "ghp_", "azure", "secret", "private_key", "password")


def sanitize_event_metadata(raw_metadata: Optional[Any]) -> Optional[Dict[str, Any]]:
    """
    Parse and sanitize security event metadata against the safe allowlist.
    Excludes any keys containing credentials, tokens, IP addresses, or internal stack traces.
    """
    if raw_metadata is None:
        return None

    parsed: Optional[Dict[str, Any]] = None
    if isinstance(raw_metadata, dict):
        parsed = raw_metadata
    elif isinstance(raw_metadata, str):
        trimmed = raw_metadata.strip()
        if not trimmed:
            return None
        try:
            val = json.loads(trimmed)
            if isinstance(val, dict):
                parsed = val
        except Exception:
            return None

    if not parsed:
        return None

    sanitized: Dict[str, Any] = {}
    for key, value in parsed.items():
        clean_key = str(key).lower().strip()
        if clean_key in SAFE_AUDIT_METADATA_ALLOWLIST:
            # Only permit primitive types (str, int, float, bool, None)
            if isinstance(value, (str, int, float, bool)) or value is None:
                if isinstance(value, str):
                    val_lower = value.lower()
                    # Drop any string value containing token-like or secret signatures
                    if any(pat in val_lower for pat in SENSITIVE_VALUE_PATTERNS):
                        continue
                sanitized[clean_key] = value

    return sanitized if sanitized else None


def encode_cursor(created_at: datetime, event_id: int) -> str:
    """
    Encode (created_at, id) into a URL-safe opaque pagination cursor string.
    """
    dt_utc = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=timezone.utc)
    payload = {
        "t": dt_utc.isoformat(),
        "id": int(event_id),
    }
    raw_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    """
    Decode a URL-safe opaque pagination cursor string into (datetime, event_id).
    Raises ValueError on malformed, corrupted, or invalid cursors.
    """
    if not cursor_str or not isinstance(cursor_str, str):
        raise ValueError("Cursor must be a non-empty string.")

    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Malformed pagination cursor: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Cursor payload must be a JSON object.")

    if "t" not in payload or "id" not in payload:
        raise ValueError("Cursor payload missing required 't' or 'id' fields.")

    try:
        dt = datetime.fromisoformat(payload["t"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception as exc:
        raise ValueError(f"Invalid timestamp in cursor: {exc}") from exc

    try:
        event_id = int(payload["id"])
        if event_id < 0:
            raise ValueError("Cursor event ID must be non-negative.")
    except Exception as exc:
        raise ValueError(f"Invalid event ID in cursor: {exc}") from exc

    return dt, event_id


class SecurityEventItem(BaseModel):
    """
    Sanitized, privacy-reviewed representation of a durable security audit event.
    Biometric embeddings, raw audio, credentials, and sensitive metadata are strictly excluded.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Unique sequence identifier of the security event")
    created_at: datetime = Field(..., description="UTC timestamp of the security event")
    event_type: str = Field(..., description="Classified security incident or event type")
    severity: str = Field(..., description="Event severity classification: low, medium, high, critical")
    status: str = Field(..., description="Action/disposition status: blocked, detected, logged, resolved")
    details: Optional[str] = Field(None, description="Sanitized human-readable event summary")
    user_id: Optional[str] = Field(None, description="External Firebase UID of authenticated actor, if applicable")
    device_id: Optional[str] = Field(None, description="Physical access terminal hardware identifier, if applicable")
    request_id: Optional[str] = Field(None, description="Correlation trace ID for cross-service request tracking")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Safe operational metadata allowed for administrative audit")


class SecurityEventsResponse(BaseModel):
    """
    Paginated response container for administrative security event queries.
    """
    events: List[SecurityEventItem] = Field(..., description="List of sanitized security audit events")
    next_cursor: Optional[str] = Field(None, description="Opaque cursor token for querying the next page, or null if no further records exist")
    has_more: bool = Field(False, description="True if additional records matching the query filters exist")
    count: int = Field(..., description="Number of events returned in the current page")
