#!/usr/bin/env python3
"""
scripts/seed_speakers.py — Safe Speaker Database Seeder (Increment 1B).

Imports the ten approved real speaker biometric profiles from
'speaker_profiles/profiles.pkl' into the persistent database using the existing
SpeakerRecord model and SpeakerRepository.

Key Guarantees:
1. Strict Validation: Enforces exactly 192-dimensional, numeric, finite (non-NaN,
   non-Inf) embeddings prior to attempting any database writes.
2. Trusted Input Only: Operates solely on local filesystem pickle files; never
   accepts arbitrary or user-uploaded pickles.
3. Excluded Identities: Excludes 'abc' and 'maam' by default; does not rename or
   infer identities.
4. Idempotency & Conflict Safety: Identical existing speaker profiles are safely
   skipped. Conflicting existing records (different embeddings, inactive status,
   or dimension mismatch) trigger an immediate atomic rollback and non-zero exit.
5. Atomic Transactions: All inserts commit together in a single transaction; if any
   insert fails, all changes are rolled back.
6. Privacy & Masking: Biometric embedding vector values and database credentials
   are strictly excluded from console logs, exception messages, and reports.
7. Preserves Caller-Owned Transactions: Methods operate within the caller's session
   contract without bypassing SpeakerRepository.
"""

from dataclasses import dataclass
import argparse
import json
import os
from pathlib import Path
import pickle
import sys
from typing import Any, Dict, List, Optional, Sequence, Set

import numpy as np
from sqlalchemy import inspect, Engine
from sqlalchemy.orm import Session

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.embeddings import (
    DEFAULT_EMBEDDING_DIM,
    serialize_embedding,
    deserialize_embedding,
)
from app.db.base import SpeakerRecord
from app.db.session import (
    get_database_url,
    mask_database_url,
    get_engine,
    get_session_factory,
)
from app.repositories.speaker_repository import SpeakerRepository


# ─── Constants & Metadata ──────────────────────────────────────────────────────

DEFAULT_PROFILES_PATH = Path("speaker_profiles/profiles.pkl")

# Ten approved real speaker identities (case-sensitive source keys)
APPROVED_SPEAKERS: List[str] = [
    "Advait",
    "Amaan Ur Raheman",
    "Krish",
    "Omar",
    "Parth",
    "Shreyas",
    "Umair",
    "Zubair",
    "abid",
    "vikas",
]

# Identities explicitly excluded from database ingestion
EXCLUDED_DEFAULT_IDENTITIES: Set[str] = {"abc", "maam"}

# Metadata conventions for approved speakers:
# - Advait, Omar, Parth: sample_count=21 based on sentence-disjoint split recorded
#   in speaker_profiles/split_info.json (sentences S01-S07 x 3 repetitions).
# - Amaan Ur Raheman, Krish, Shreyas, Umair, Zubair, abid, vikas: sample_count=5
#   based on 5 enrollment recordings in processed_dataset/.
APPROVED_SPEAKER_METADATA: Dict[str, Dict[str, Any]] = {
    "Advait": {
        "full_name": "Advait",
        "sample_count": 21,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "sentence_disjoint",
            "reference_sentences": "S01-S07 (3 repetitions each)",
            "split_ref": "speaker_profiles/split_info.json",
        },
    },
    "Amaan Ur Raheman": {
        "full_name": "Amaan Ur Raheman",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/Amaan Ur Raheman (5 files)",
        },
    },
    "Krish": {
        "full_name": "Krish",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/Krish (5 files)",
        },
    },
    "Omar": {
        "full_name": "Omar",
        "sample_count": 21,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "sentence_disjoint",
            "reference_sentences": "S01-S07 (3 repetitions each)",
            "split_ref": "speaker_profiles/split_info.json",
        },
    },
    "Parth": {
        "full_name": "Parth",
        "sample_count": 21,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "sentence_disjoint",
            "reference_sentences": "S01-S07 (3 repetitions each)",
            "split_ref": "speaker_profiles/split_info.json",
        },
    },
    "Shreyas": {
        "full_name": "Shreyas",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/Shreyas (5 files)",
        },
    },
    "Umair": {
        "full_name": "Umair",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/Umair (5 files)",
        },
    },
    "Zubair": {
        "full_name": "Zubair",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/Zubair (5 files)",
        },
    },
    "abid": {
        "full_name": "abid",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/abid (5 files)",
        },
    },
    "vikas": {
        "full_name": "vikas",
        "sample_count": 5,
        "metadata": {
            "source": "speaker_profiles/profiles.pkl",
            "enrollment_strategy": "fixed_enrollment_recordings",
            "reference_recordings": "processed_dataset/vikas (5 files)",
        },
    },
}


# ─── Exceptions & Results ──────────────────────────────────────────────────────

class SeederError(Exception):
    """Base exception for speaker database seeder errors."""
    pass


class SeederValidationError(SeederError, ValueError):
    """Raised when profile validation or embedding validation fails."""
    pass


class SeederConflictError(SeederError, ValueError):
    """Raised when existing database state conflicts with intended seed data."""
    pass


@dataclass(frozen=True)
class SeedResult:
    """Summary outcome of a database seeding operation."""
    total_approved: int
    inserted: List[str]
    skipped: List[str]
    dry_run: bool

    @property
    def insert_count(self) -> int:
        return len(self.inserted)

    @property
    def skip_count(self) -> int:
        return len(self.skipped)


# ─── Validation & Loading ──────────────────────────────────────────────────────

def load_and_validate_profiles(
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    approved_speakers: Sequence[str] = APPROVED_SPEAKERS,
) -> Dict[str, np.ndarray]:
    """
    Safely load and validate the trusted local speaker profiles pickle file.

    Guarantees:
    - Path must exist and point to a readable local file.
    - Loaded object must be a dictionary.
    - All approved speaker identities must be present.
    - Excluded identities (e.g. 'abc', 'maam') are ignored.
    - Every approved embedding is validated as 192-dimensional, numeric, and finite.
    - Embeddings must be serializable to JSON without error.
    - Biometric vector numbers are NEVER leaked in logs or exception messages.

    Returns:
        Dict mapping approved speaker identity to validated float32 NumPy array.
    """
    path = Path(profiles_path)
    if not path.is_file():
        raise FileNotFoundError(f"Speaker profiles file not found: {path}")

    try:
        with open(path, "rb") as f:
            profiles = pickle.load(f)
    except Exception as exc:
        raise SeederValidationError(f"Failed to read profiles pickle file: {type(exc).__name__}") from exc

    if not isinstance(profiles, dict):
        raise SeederValidationError(
            f"Expected dictionary in profiles file, got {type(profiles).__name__}."
        )

    # Verify all approved speaker keys exist
    missing_keys = [k for k in approved_speakers if k not in profiles]
    if missing_keys:
        raise SeederValidationError(
            f"Profiles file is missing {len(missing_keys)} approved speaker key(s): {missing_keys}"
        )

    validated: Dict[str, np.ndarray] = {}
    for speaker_id in approved_speakers:
        raw_vec = profiles[speaker_id]
        try:
            # Validate and serialize via existing module
            serialized_json = serialize_embedding(raw_vec, expected_dim=DEFAULT_EMBEDDING_DIM)
            # Verify clean deserialization into float32 array
            deserialized_vec = deserialize_embedding(serialized_json, expected_dim=DEFAULT_EMBEDDING_DIM)
            if deserialized_vec is None:
                raise ValueError("Deserialized embedding vector is unexpectedly None.")
            validated[speaker_id] = deserialized_vec
        except Exception as exc:
            raise SeederValidationError(
                f"Biometric validation failed for approved speaker '{speaker_id}': {exc}"
            ) from exc

    return validated


def check_database_readiness(engine: Engine, masked_url: str) -> None:
    """
    Verify that the database is reachable and that required tables exist.
    Fails closed if Alembic migrations have not been applied.
    """
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            if not inspector.has_table("speakers"):
                raise RuntimeError(
                    f"Database at {masked_url} is missing the required 'speakers' table. "
                    f"Please apply database migrations first: 'alembic upgrade head'."
                )
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(
            f"Failed to connect to database at {masked_url}: {type(exc).__name__}"
        ) from exc


# ─── Core Seeder Engine ────────────────────────────────────────────────────────

def seed_speakers(
    session: Session,
    validated_profiles: Dict[str, np.ndarray],
    dry_run: bool = False,
    approved_speakers: Sequence[str] = APPROVED_SPEAKERS,
) -> SeedResult:
    """
    Inspect existing records and safely seed approved speakers into the session.

    Caller-owned transaction contract:
    - This function performs flushes via SpeakerRepository.create(), but does NOT commit.
    - If dry_run is True, no records are created or flushed.
    - If any conflict is detected, SeederConflictError is raised and no writes occur.

    Conflict Rules:
    - An existing speaker record with identical embedding and active status is skipped.
    - An existing speaker record with a different embedding, missing embedding,
      inactive status (suspended/revoked), or different dimension is treated as a conflict.
    """
    repo = SpeakerRepository(session)
    to_insert: List[str] = []
    to_skip: List[str] = []
    conflicts: List[str] = []

    for speaker_id in approved_speakers:
        target_vec = validated_profiles[speaker_id]
        existing = repo.get_by_speaker_id(speaker_id)

        if existing is None:
            to_insert.append(speaker_id)
            continue

        # Existing record found — verify identity compatibility
        existing_vec = repo.get_embedding(speaker_id)
        is_embedding_identical = (
            existing_vec is not None
            and np.allclose(existing_vec, target_vec, rtol=1e-5, atol=1e-6)
        )
        is_status_active = (existing.status == "active")
        is_dim_match = (existing.embedding_dim == DEFAULT_EMBEDDING_DIM)

        if is_embedding_identical and is_status_active and is_dim_match:
            to_skip.append(speaker_id)
        else:
            conflicts.append(speaker_id)

    if conflicts:
        raise SeederConflictError(
            f"Conflicting existing speaker record(s) detected for: {conflicts}. "
            f"Database record differs in embedding, status, or dimensions from seed data. "
            f"Aborting transaction to protect biometric integrity."
        )

    if dry_run:
        return SeedResult(
            total_approved=len(approved_speakers),
            inserted=to_insert,
            skipped=to_skip,
            dry_run=True,
        )

    # Perform atomic creation of missing speakers
    for speaker_id in to_insert:
        meta_info = APPROVED_SPEAKER_METADATA.get(speaker_id, {})
        full_name = meta_info.get("full_name", speaker_id)
        sample_count = meta_info.get("sample_count", 1)
        raw_meta = meta_info.get("metadata")
        metadata_json = json.dumps(raw_meta) if raw_meta else None
        target_vec = validated_profiles[speaker_id]

        repo.create(
            speaker_id=speaker_id,
            full_name=full_name,
            status="active",
            embedding_dim=DEFAULT_EMBEDDING_DIM,
            sample_count=sample_count,
            metadata_json=metadata_json,
            embedding=target_vec,
        )

    return SeedResult(
        total_approved=len(approved_speakers),
        inserted=to_insert,
        skipped=to_skip,
        dry_run=False,
    )


def run_seed_speakers(
    profiles_path: Path = DEFAULT_PROFILES_PATH,
    dry_run: bool = False,
    database_url: Optional[str] = None,
) -> SeedResult:
    """
    High-level entry point orchestrating profile validation, database connectivity,
    atomic transaction management, and execution of the speaker seeder.
    """
    target_url = database_url or get_database_url()
    masked_url = mask_database_url(target_url)

    engine = get_engine(target_url)
    check_database_readiness(engine, masked_url)

    validated_profiles = load_and_validate_profiles(profiles_path)

    session_factory = get_session_factory(target_url)
    session = session_factory()

    try:
        result = seed_speakers(
            session=session,
            validated_profiles=validated_profiles,
            dry_run=dry_run,
        )
        if dry_run:
            session.rollback()
        else:
            session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── CLI Entry Point ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "VoiceLock Enterprise — Safe Speaker Database Seeder (Increment 1B).\n\n"
            "Safely imports the ten approved real speaker biometric profiles from\n"
            "speaker_profiles/profiles.pkl into the database using SpeakerRepository.\n"
            "Ensures idempotency, atomic commits, and credential/vector privacy."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profiles-path",
        type=Path,
        default=DEFAULT_PROFILES_PATH,
        help=f"Path to speaker profiles pickle file (default: {DEFAULT_PROFILES_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate profiles and report planned database actions without committing changes.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Optional database URL override. Defaults to configured DATABASE_URL or local SQLite.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main CLI execution routine."""
    parser = build_parser()
    args = parser.parse_args(argv)

    target_url = args.db_url or get_database_url()
    masked_url = mask_database_url(target_url)
    mode_str = "DRY RUN (no database writes)" if args.dry_run else "EXECUTE (atomic commit)"

    print("=" * 60)
    print("  VoiceLock Enterprise — Speaker Database Seeder")
    print("=" * 60)
    print(f"Target Database:  {masked_url}")
    print(f"Execution Mode:   {mode_str}")
    print(f"Profiles Source:  {args.profiles_path}")
    print()

    try:
        result = run_seed_speakers(
            profiles_path=args.profiles_path,
            dry_run=args.dry_run,
            database_url=args.db_url,
        )
    except FileNotFoundError as exc:
        print(f"✗ File Error: {exc}", file=sys.stderr)
        return 1
    except SeederValidationError as exc:
        print(f"✗ Validation Error: {exc}", file=sys.stderr)
        return 1
    except SeederConflictError as exc:
        print(f"✗ Conflict Error: {exc}", file=sys.stderr)
        print("  Transaction rolled back. No database modifications were applied.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"✗ Database Readiness Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"✗ Unexpected Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("Validation:")
    print(f"  ✓ {result.total_approved} approved speaker profiles validated (192-d, finite)")
    print("  ✓ Excluded default identities: abc, maam")
    print()
    print("Database State:")
    if result.inserted:
        print(f"  • To insert ({result.insert_count}): {', '.join(result.inserted)}")
    else:
        print("  • To insert (0): (none)")

    if result.skipped:
        print(f"  • To skip ({result.skip_count}):   {', '.join(result.skipped)}")
    else:
        print("  • To skip (0):   (none)")
    print()

    print("Outcome:")
    if result.dry_run:
        print(f"  [DRY RUN] Validation succeeded. {result.insert_count} records would be inserted.")
        print("  [DRY RUN] Zero modifications committed to database.")
    else:
        if result.insert_count > 0:
            print(f"  ✓ Successfully seeded {result.insert_count} speaker record(s).")
            print("  ✓ Transaction committed atomically.")
        else:
            print("  ✓ All approved speaker records are already synchronized and identical.")
            print("  ✓ Zero new records required.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
