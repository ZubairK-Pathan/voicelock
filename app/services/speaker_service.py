"""
app/services/speaker_service.py — Database-backed speaker profile and biometric service.

Guarantees:
1. Database-Backed Identity: Obtains speaker records and 192-dimensional embeddings
   strictly through the database/session/repository architecture.
2. Safe Deserialization: Reuses app.core.embeddings for validation and deserialization
   into float32 NumPy arrays.
3. No Pickle Fallback in Production: Never silently falls back to local pickle files
   if the database is empty or unavailable.
4. Transaction Isolation: Operates within the caller's scoped SQLAlchemy Session;
   avoids global mutable ORM sessions or sharing sessions across concurrent requests.
5. Inactive & Corrupt Handling: Inactive speakers (suspended/revoked) and corrupt
   embeddings are filtered out safely without exposing vector values.
6. Fail-Closed Resilience: Database errors raise SpeakerServiceDatabaseError and fail closed.
7. Cached ML Inference: Reuses SpeechBrain ECAPA-TDNN model singleton across requests
   without redundant in-memory reloads.
"""

import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple, Union, Any
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
import torch

from app.core.config import SERVER_THRESHOLD
from app.core.embeddings import (
    DEFAULT_EMBEDDING_DIM,
    deserialize_embedding,
    serialize_embedding,
)
from app.db.base import SpeakerRecord
from app.db.session import get_db_context
from app.repositories.speaker_repository import SpeakerRepository, DuplicateSpeakerError
from audio_utils import (
    load_audio,
    normalize_audio,
    generate_embedding,
    load_embedding_model,
    get_device,
    TARGET_SAMPLE_RATE,
)
import predict


# ─── Custom Exceptions ─────────────────────────────────────────────────────────

class SpeakerServiceError(Exception):
    """Base exception for database speaker service operations."""
    pass


class SpeakerNotFoundError(SpeakerServiceError, KeyError):
    """Raised when a requested speaker identity is not found in the database."""
    pass


class InactiveSpeakerError(SpeakerServiceError, ValueError):
    """Raised when an enrolled speaker has been suspended or revoked."""
    pass


class MissingSpeakerEmbeddingError(SpeakerServiceError, ValueError):
    """Raised when a speaker record exists but has no biometric embedding stored."""
    pass


class EmptySpeakerRegistryError(SpeakerServiceError, ValueError):
    """Raised when the database contains no active speaker profiles with valid embeddings."""
    pass


class SpeakerServiceDatabaseError(SpeakerServiceError):
    """Raised when a database query or connection fails."""
    pass


# ─── Global ML Model Singleton ────────────────────────────────────────────────

_classifier = None


def get_classifier():
    """
    Return cached SpeechBrain ECAPA-TDNN classifier singleton.
    Thread-safe inference on CPU. Loaded once per process lifecycle.
    """
    global _classifier
    if _classifier is None:
        device = get_device()
        _classifier = load_embedding_model(device)
    return _classifier


def set_classifier_for_testing(classifier):
    """Allow injecting mock classifier in unit tests."""
    global _classifier
    _classifier = classifier


def reset_classifier_for_testing():
    """Reset cached classifier singleton between test runs."""
    global _classifier
    _classifier = None


# ─── Database-Backed Speaker Service ──────────────────────────────────────────

class SpeakerService:
    """
    Database-backed speaker service managing speaker profile queries,
    vector deserialization, and biometric identification/verification.
    Operates strictly within the caller-provided SQLAlchemy Session.
    """

    def __init__(self, session: Session):
        if session is None:
            raise ValueError("SpeakerService requires an active SQLAlchemy Session.")
        self.session = session
        self.repo = SpeakerRepository(session)

    def get_registered_speakers(self) -> List[str]:
        """
        Return a sorted list of active speaker IDs from the database.
        Raises SpeakerServiceDatabaseError on database failure.
        """
        try:
            return self.repo.get_active_speaker_ids()
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError("Database error while retrieving active speaker list.") from exc

    def get_speaker_record(self, speaker_id: str) -> Optional[SpeakerRecord]:
        """
        Look up a speaker record by speaker_id.
        Raises SpeakerServiceDatabaseError on database failure.
        """
        try:
            return self.repo.get_by_speaker_id(speaker_id)
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError(f"Database error while looking up speaker '{speaker_id}'.") from exc

    def is_speaker_active(self, speaker_id: str) -> bool:
        """
        Check if a speaker is registered and active in the database.
        Returns False if speaker is not found, suspended, or revoked.
        Raises SpeakerServiceDatabaseError on database failure.
        """
        try:
            record = self.repo.get_by_speaker_id(speaker_id)
            return record is not None and record.status == "active"
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError(f"Database error while checking speaker '{speaker_id}'.") from exc

    def get_speaker_embedding(self, speaker_id: str) -> Optional[np.ndarray]:
        """
        Retrieve and deserialize the 192-d float32 biometric embedding for an active speaker.
        Returns None if:
        - Speaker is not found
        - Speaker is inactive (suspended or revoked)
        - Speaker has no embedding stored (embedding_json is None or empty)
        - Embedding fails deserialization/validation
        Raises SpeakerServiceDatabaseError on database failure.
        """
        try:
            record = self.repo.get_by_speaker_id(speaker_id)
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError(f"Database error while retrieving embedding for '{speaker_id}'.") from exc

        if record is None or record.status != "active" or not record.embedding_json:
            return None

        try:
            return deserialize_embedding(record.embedding_json, expected_dim=record.embedding_dim)
        except Exception:
            # Corrupt or invalid embedding stored in DB — safely fail closed without exposing vector values
            return None

    def get_active_profiles(self) -> Dict[str, np.ndarray]:
        """
        Retrieve dictionary mapping speaker_id -> 192-d float32 vector
        for all active speakers in the database with valid embeddings.
        Inactive speakers, missing embeddings, and malformed embeddings are safely excluded.
        Raises SpeakerServiceDatabaseError on database failure.
        """
        try:
            records = self.repo.list_speakers(active_only=True)
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError("Database error while retrieving speaker profiles.") from exc

        profiles: Dict[str, np.ndarray] = {}
        for record in records:
            if not record.embedding_json:
                continue
            try:
                vec = deserialize_embedding(record.embedding_json, expected_dim=record.embedding_dim)
                if vec is not None:
                    profiles[record.speaker_id] = vec
            except Exception:
                # Omit corrupt embeddings safely
                continue

        return profiles

    def identify_speaker(
        self,
        audio_path: str,
        threshold: float = SERVER_THRESHOLD,
        classifier=None,
    ) -> dict:
        """
        Perform 1-to-N speaker identification against active database profiles.
        Reuses predict.predict_speaker.
        Raises EmptySpeakerRegistryError if no active profiles exist.
        """
        profiles = self.get_active_profiles()
        if not profiles:
            raise EmptySpeakerRegistryError("No speaker profiles are enrolled in the system.")

        clf = classifier or get_classifier()
        return predict.predict_speaker(
            audio_path=audio_path,
            threshold=threshold,
            classifier=clf,
            profiles=profiles,
            verbose=False,
        )

    def verify_speaker(
        self,
        audio_path: str,
        claimed_identity: str,
        threshold: float = SERVER_THRESHOLD,
        classifier=None,
    ) -> dict:
        """
        Perform 1-to-1 speaker verification against the claimed identity in the database.
        Reuses predict.verify_speaker with target profile vector.
        Raises SpeakerNotFoundError if claimed identity is unknown.
        Raises InactiveSpeakerError if speaker is suspended or revoked.
        Raises MissingSpeakerEmbeddingError if speaker lacks an enrolled voiceprint.
        """
        clean_identity = claimed_identity.strip()
        record = self.get_speaker_record(clean_identity)
        if record is None:
            raise SpeakerNotFoundError(f"Speaker '{clean_identity}' is not registered.")
        if record.status != "active":
            raise InactiveSpeakerError(f"Speaker '{clean_identity}' is inactive.")

        target_vec = self.get_speaker_embedding(clean_identity)
        if target_vec is None:
            raise MissingSpeakerEmbeddingError(f"Speaker '{clean_identity}' has no biometric voiceprint enrolled.")

        clf = classifier or get_classifier()
        return predict.verify_speaker(
            audio_path=audio_path,
            claimed_identity=clean_identity,
            threshold=threshold,
            classifier=clf,
            profiles={clean_identity: target_vec},
            verbose=False,
        )

    def enroll_speaker(
        self,
        speaker_id: str,
        full_name: Optional[str] = None,
        audio_paths: Optional[List[Union[str, Path]]] = None,
        enrolled_by: Optional[str] = None,
        classifier=None,
    ) -> SpeakerRecord:
        """
        Enroll a new speaker profile by aggregating 3 to 10 audio samples into a 192-d centroid embedding.
        Persists the record in the database using SpeakerRepository within the caller's session.
        Does NOT commit the transaction (caller owns commit/rollback).
        """
        if not speaker_id or not speaker_id.strip():
            raise ValueError("speaker_id must be a non-empty string.")

        clean_id = speaker_id.strip()
        if not (2 <= len(clean_id) <= 64):
            raise ValueError(f"speaker_id length ({len(clean_id)}) must be between 2 and 64 characters.")

        if not re.match(r"^[A-Za-z0-9_\- ]+$", clean_id):
            raise ValueError(
                "speaker_id may only contain alphanumeric characters, spaces, hyphens, and underscores."
            )

        clean_full_name = full_name.strip() if full_name and full_name.strip() else None
        if clean_full_name and len(clean_full_name) > 128:
            raise ValueError("full_name must be 128 characters or fewer.")

        # Check for case-insensitive duplicate in database
        try:
            stmt = select(SpeakerRecord).where(func.lower(SpeakerRecord.speaker_id) == clean_id.lower())
            existing = self.session.scalar(stmt)
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError(f"Database error while checking duplicate for '{clean_id}'.") from exc

        if existing is not None:
            raise DuplicateSpeakerError(f"Speaker with speaker_id '{clean_id}' already exists.")

        # Validate sample count (3 to 10)
        if not audio_paths or len(audio_paths) < 3:
            raise ValueError(
                f"At least 3 audio samples are required for enrollment (got {len(audio_paths) if audio_paths else 0})."
            )
        if len(audio_paths) > 10:
            raise ValueError(
                f"At most 10 audio samples are allowed for enrollment (got {len(audio_paths)})."
            )

        clf = classifier or get_classifier()
        embeddings: List[np.ndarray] = []
        durations: List[float] = []

        for idx, path in enumerate(audio_paths):
            p = Path(path)
            if not p.exists():
                raise ValueError(f"Sample {idx + 1} file not found: {p}")

            try:
                waveform, sr = load_audio(p, target_sr=TARGET_SAMPLE_RATE)
            except Exception as exc:
                raise ValueError(f"Sample {idx + 1} audio could not be decoded: {exc}") from exc

            # Validate duration: 1.0s to 30.0s
            num_samples = waveform.shape[-1]
            duration_sec = float(num_samples) / float(sr)
            if duration_sec < 1.0 or duration_sec > 30.0:
                raise ValueError(
                    f"Sample {idx + 1} duration ({duration_sec:.2f}s) must be between 1.0 and 30.0 seconds."
                )

            # Validate audio energy / non-silence
            max_amp = float(waveform.abs().max())
            rms = float(torch.sqrt(torch.mean(waveform ** 2)))
            if max_amp < 0.01 or rms < 0.001:
                raise ValueError(
                    f"Sample {idx + 1} contains insufficient audio energy or silence (peak: {max_amp:.4f}, RMS: {rms:.5f})."
                )

            # Peak normalize and extract embedding
            norm_waveform = normalize_audio(waveform)
            emb = generate_embedding(clf, norm_waveform, sr)
            emb_arr = np.asarray(emb, dtype=np.float32)
            if emb_arr.shape != (DEFAULT_EMBEDDING_DIM,):
                raise ValueError(f"Sample {idx + 1} generated invalid embedding dimension: {emb_arr.shape}")

            embeddings.append(emb_arr)
            durations.append(round(duration_sec, 2))

        # Centroid embedding aggregation
        profile_embedding = np.mean(embeddings, axis=0).astype(np.float32)

        metadata = {
            "enrolled_by": enrolled_by,
            "sample_count": len(embeddings),
            "sample_durations": durations,
        }

        try:
            return self.repo.create(
                speaker_id=clean_id,
                full_name=clean_full_name,
                status="active",
                embedding_dim=DEFAULT_EMBEDDING_DIM,
                sample_count=len(embeddings),
                embedding=profile_embedding,
                metadata_json=json.dumps(metadata),
            )
        except DuplicateSpeakerError:
            raise
        except SQLAlchemyError as exc:
            raise SpeakerServiceDatabaseError(f"Database error while saving speaker profile '{clean_id}'.") from exc


# ─── Backward-Compatible Helpers ───────────────────────────────────────────────

def get_system(session: Optional[Session] = None) -> Tuple[Dict[str, np.ndarray], Any]:
    """
    Return (profiles_dict, classifier) tuple.
    Obtains active profiles from the database using the provided session,
    or via a temporary scoped session if session is None.
    Does NOT load local pickle files.
    """
    classifier = get_classifier()
    if session is not None:
        service = SpeakerService(session)
        profiles = service.get_active_profiles()
    else:
        with get_db_context() as db:
            service = SpeakerService(db)
            profiles = service.get_active_profiles()
    return profiles, classifier


def get_profiles(session: Optional[Session] = None) -> Dict[str, np.ndarray]:
    """Return dictionary of active speaker profiles from the database."""
    profiles, _ = get_system(session)
    return profiles


def reload_profiles() -> Dict[str, np.ndarray]:
    """Reload active speaker profiles from the database."""
    return get_profiles()
