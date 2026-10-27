#!/usr/bin/env python3
"""
scripts/register_device.py — Secure Hardware Terminal Provisioning CLI.

Provisions physical access terminals (IoT devices, e.g. ESP32) into the
VoiceLock database using the existing DeviceRecord schema and DeviceRepository.

Security Invariants:
1. Cryptographic Entropy: Generates secrets using Python's `secrets` module (CSPRNG, >= 256 bits).
2. Zero Plaintext In Database: Only one-way cryptographic verifiers (SHA-256 hash formatted
   as 'sha256$<hex_digest>') are stored in the database `secret_hash` column.
3. Database Safety: Defaults strictly to local SQLite ('sqlite:///./voicelock.db').
   Rejects remote databases (PostgreSQL, Neon) unless explicitly confirmed via `--allow-remote`.
4. Credential Masking: Database passwords and credentials are never printed or logged.
5. Key Rotation Support: Supports graceful key rotation via `--rotate-key` which updates
   `secret_hash`, increments `key_version`, and updates `updated_at`.
6. ESP32 Header Generation: Optionally outputs a secure C/C++ header ('credentials.h')
   with file mode 0600 (read/write by owner only).
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any, Dict, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy.orm import sessionmaker
from app.core.device_auth import hash_device_secret, verify_device_secret_hash
from app.db.base import Base, DeviceRecord
from app.db.session import (
    create_db_engine,
    mask_database_url,
    normalize_database_url,
)
from app.repositories.device_repository import (
    DeviceRepository,
    DuplicateDeviceError,
    DeviceNotFoundError,
)

DEFAULT_LOCAL_DB_URL = "sqlite:///./voicelock.db"


def is_remote_database(url: str) -> bool:
    """Return True if the database URL points to a remote/cloud database (Postgres, Neon, etc.)."""
    clean = url.strip().lower()
    return (
        clean.startswith("postgres://")
        or clean.startswith("postgresql://")
        or clean.startswith("postgresql+")
        or "neon.tech" in clean
        or "aws" in clean
    )


def generate_device_secret(num_bytes: int = 32) -> str:
    """Generate a high-entropy cryptographically secure device secret (token_urlsafe)."""
    return secrets.token_urlsafe(num_bytes)


def generate_c_header(
    device_id: str,
    secret: str,
    server_url: str = "http://192.168.1.100:8000",
) -> str:
    """Generate C/C++ header content for ESP32 firmware."""
    return f"""#ifndef VOICELOCK_CREDENTIALS_H
#define VOICELOCK_CREDENTIALS_H

// Auto-generated hardware terminal credentials — VoiceLock Enterprise
// DO NOT COMMIT THIS FILE TO VERSION CONTROL

constexpr const char* DEVICE_ID     = "{device_id}";
constexpr const char* DEVICE_SECRET = "{secret}";
constexpr const char* SERVER_URL    = "{server_url}";

#endif // VOICELOCK_CREDENTIALS_H
"""


def register_device(
    db_url: str = DEFAULT_LOCAL_DB_URL,
    device_id: str = "terminal-gate-01",
    name: Optional[str] = None,
    status: str = "active",
    key_version: int = 1,
    secret: Optional[str] = None,
    allow_remote: bool = False,
    rotate_key: bool = False,
    metadata_json: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Provision or rotate a device in the target database.
    
    Returns a dictionary summarizing the operation.
    """
    clean_device_id = device_id.strip()
    if not clean_device_id:
        raise ValueError("device_id must be a non-empty string.")

    if is_remote_database(db_url) and not allow_remote:
        raise PermissionError(
            f"Remote database write blocked for safety ({mask_database_url(db_url)}). "
            "Pass --allow-remote to explicitly authorize remote provisioning."
        )

    # Resolve or generate secret
    raw_secret = secret.strip() if secret and secret.strip() else generate_device_secret()
    secret_hash = hash_device_secret(raw_secret)

    normalized_url = normalize_database_url(db_url)
    engine = create_db_engine(normalized_url)

    # Ensure schema exists (especially for local SQLite)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()

    try:
        repo = DeviceRepository(session)
        existing = repo.get_by_device_id(clean_device_id)

        if existing is not None:
            # Check if secret already matches
            if verify_device_secret_hash(raw_secret, existing.secret_hash):
                action = "skipped_identical"
                result = {
                    "device_id": existing.device_id,
                    "name": existing.name,
                    "status": existing.status,
                    "key_version": existing.key_version,
                    "secret_hash": existing.secret_hash,
                    "secret": raw_secret,
                    "db_url": mask_database_url(db_url),
                    "action": action,
                    "message": f"Device '{clean_device_id}' already registered with matching credentials.",
                }
                return result

            if not rotate_key:
                raise DuplicateDeviceError(
                    f"Device '{clean_device_id}' already exists in database with different credentials. "
                    "Use --rotate-key to rotate its credentials."
                )

            # Key rotation requested
            new_version = existing.key_version + 1
            if not dry_run:
                existing.secret_hash = secret_hash
                existing.key_version = new_version
                if name:
                    existing.name = name.strip()
                if status:
                    existing.status = status
                if metadata_json:
                    existing.metadata_json = metadata_json
                session.flush()
                session.commit()

            action = "rotated"
            result = {
                "device_id": existing.device_id,
                "name": existing.name,
                "status": existing.status,
                "key_version": new_version if not dry_run else existing.key_version + 1,
                "secret_hash": secret_hash,
                "secret": raw_secret,
                "db_url": mask_database_url(db_url),
                "action": action,
                "dry_run": dry_run,
                "message": f"Device '{clean_device_id}' credentials rotated to key version {new_version}.",
            }
            return result

        # Create new record
        if not dry_run:
            record = repo.create(
                device_id=clean_device_id,
                secret_hash=secret_hash,
                name=name.strip() if name else None,
                status=status,
                key_version=key_version,
                metadata_json=metadata_json,
            )
            session.commit()
            assigned_version = record.key_version
            assigned_status = record.status
        else:
            assigned_version = key_version
            assigned_status = status

        action = "created"
        result = {
            "device_id": clean_device_id,
            "name": name.strip() if name else None,
            "status": assigned_status,
            "key_version": assigned_version,
            "secret_hash": secret_hash,
            "secret": raw_secret,
            "db_url": mask_database_url(db_url),
            "action": action,
            "dry_run": dry_run,
            "message": f"Device '{clean_device_id}' provisioned successfully.",
        }
        return result

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


def write_header_file(header_path: Path, content: str) -> None:
    """Write C/C++ header file with restrictive file permissions (0600)."""
    header_path.parent.mkdir(parents=True, exist_ok=True)
    header_path.write_text(content, encoding="utf-8")
    header_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="VoiceLock Enterprise — Secure Hardware Terminal Provisioning CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--device-id",
        type=str,
        default="terminal-gate-01",
        help="Unique identifier for the hardware terminal.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="Main Entrance Terminal",
        help="Human-readable physical location or name.",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="active",
        choices=["active", "suspended", "revoked"],
        help="Initial lifecycle status.",
    )
    parser.add_argument(
        "--key-version",
        type=int,
        default=1,
        help="Initial key version.",
    )
    parser.add_argument(
        "--secret",
        type=str,
        default=None,
        help="Pre-defined secret key. If omitted, a cryptographically secure 256-bit secret is generated.",
    )
    parser.add_argument(
        "--rotate-key",
        action="store_true",
        help="Rotate credentials if device already exists.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=DEFAULT_LOCAL_DB_URL,
        help="Database connection URL. Defaults strictly to local SQLite.",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Explicitly permit writing to a remote/cloud database.",
    )
    parser.add_argument(
        "--output-header",
        type=str,
        default=None,
        help="Path to generate C/C++ 'credentials.h' header file for ESP32 firmware.",
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default="http://192.168.1.100:8000",
        help="API base URL to embed in the generated C/C++ header file.",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default=None,
        help="Optional JSON string of terminal metadata (e.g. MAC address, building zone).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate provisioning without writing to the database.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )

    args = parser.parse_args(argv)

    try:
        result = register_device(
            db_url=args.db_url,
            device_id=args.device_id,
            name=args.name,
            status=args.status,
            key_version=args.key_version,
            secret=args.secret,
            allow_remote=args.allow_remote,
            rotate_key=args.rotate_key,
            metadata_json=args.metadata,
            dry_run=args.dry_run,
        )

        if args.output_header and not args.dry_run:
            header_path = Path(args.output_header)
            header_content = generate_c_header(
                device_id=result["device_id"],
                secret=result["secret"],
                server_url=args.server_url,
            )
            write_header_file(header_path, header_content)
            result["header_file"] = str(header_path)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("=" * 64)
            print("VOICELOCK HARDWARE TERMINAL PROVISIONING")
            print("=" * 64)
            print(f"Status           : {result['message']}")
            print(f"Action           : {result['action']}")
            print(f"Device ID        : {result['device_id']}")
            print(f"Terminal Name    : {result['name']}")
            print(f"Lifecycle Status : {result['status']}")
            print(f"Key Version      : {result['key_version']}")
            print(f"Secret Verifier  : {result['secret_hash']}")
            print(f"Target Database  : {result['db_url']}")
            if "header_file" in result:
                print(f"Header Exported  : {result['header_file']} (mode 0600)")
            print("-" * 64)
            print("DEVICE PROVISIONING SECRET (DO NOT COMMIT):")
            print(f"  {result['secret']}")
            print("=" * 64)

        return 0

    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
        else:
            print(f"\n[ERROR] Provisioning failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
