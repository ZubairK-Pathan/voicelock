"""
tests/test_seed_speakers.py — Comprehensive test suite for Safe Speaker Database Seeder (Increment 1B).

Covers:
1. Successful seeding into a temporary test database using synthetic embeddings.
2. Accurate metadata assignment (sample_count 21 for Advait/Omar/Parth, 5 for others).
3. Zero ingestion of excluded identities ('abc', 'maam').
4. Strict validation rejection: missing files, missing approved keys, wrong dimensions, NaN/Inf.
5. Dry-run mode: validation and reporting without persistent writes.
6. Idempotency: rerunning seeder safely skips existing identical records without duplicates.
7. Conflict safety: conflicting embeddings or statuses abort the entire transaction.
8. Unrelated records: existing non-approved speakers remain untouched.
9. Atomic rollback: midway insert failures rollback all records.
10. Firebase isolation: no user-to-speaker authorization mappings are created.
11. Unreachable databases or unmigrated schemas fail closed.
12. CLI entry point execution and exit code contracts.
"""

from pathlib import Path
import pickle
import tempfile
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base, SpeakerRecord, UserSpeakerMapping
from app.db.session import create_db_engine, reset_engine
from scripts.seed_speakers import (
    APPROVED_SPEAKERS,
    APPROVED_SPEAKER_METADATA,
    DEFAULT_EMBEDDING_DIM,
    EXCLUDED_DEFAULT_IDENTITIES,
    SeederConflictError,
    SeederValidationError,
    check_database_readiness,
    load_and_validate_profiles,
    main,
    run_seed_speakers,
    seed_speakers,
)
from app.repositories.speaker_repository import SpeakerRepository


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_engine():
    """Ensure engine singletons are disposed between test runs."""
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def test_db():
    """Create a temporary SQLite database initialized with all tables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        db_path = Path(tmp_file.name)

    db_url = f"sqlite:///{db_path}"
    engine = create_db_engine(db_url)
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    try:
        yield {"url": db_url, "engine": engine, "session_factory": session_factory}
    finally:
        engine.dispose()
        if db_path.exists():
            try:
                db_path.unlink()
            except OSError:
                pass


@pytest.fixture
def synthetic_profiles(tmp_path):
    """
    Generate a temporary profiles.pkl containing synthetic 192-d vectors
    for all 10 approved speakers plus the excluded identities ('abc', 'maam').
    Uses reproducible pseudo-random numbers without real participant data.
    """
    rng = np.random.RandomState(42)
    profiles = {}

    for idx, speaker in enumerate(APPROVED_SPEAKERS):
        # Generate normalized-like synthetic 192-d float32 vector
        vec = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
        vec /= np.linalg.norm(vec)
        profiles[speaker] = vec

    # Add excluded identities
    for exc in EXCLUDED_DEFAULT_IDENTITIES:
        vec = rng.randn(DEFAULT_EMBEDDING_DIM).astype(np.float32)
        vec /= np.linalg.norm(vec)
        profiles[exc] = vec

    pkl_path = tmp_path / "synthetic_profiles.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(profiles, f)

    return {"path": pkl_path, "profiles": profiles}


# ─── 1. Validation & Loading Tests ─────────────────────────────────────────────

def test_load_and_validate_synthetic_profiles(synthetic_profiles):
    """Verify loading and validating all approved profiles with synthetic data."""
    validated = load_and_validate_profiles(synthetic_profiles["path"])
    assert len(validated) == len(APPROVED_SPEAKERS)
    for speaker in APPROVED_SPEAKERS:
        assert speaker in validated
        assert validated[speaker].shape == (192,)
        assert validated[speaker].dtype == np.float32

    # Excluded identities must not be present in validated output
    for exc in EXCLUDED_DEFAULT_IDENTITIES:
        assert exc not in validated


def test_missing_profile_file_raises():
    """Attempting to load a non-existent file must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_and_validate_profiles(Path("/nonexistent/path/profiles.pkl"))


def test_top_level_not_a_dict_raises(tmp_path):
    """Pickle files not containing a dict must be rejected."""
    bad_pkl = tmp_path / "bad.pkl"
    with open(bad_pkl, "wb") as f:
        pickle.dump(["not", "a", "dict"], f)

    with pytest.raises(SeederValidationError, match="Expected dictionary"):
        load_and_validate_profiles(bad_pkl)


def test_missing_approved_speaker_key_raises(tmp_path):
    """Pickle files missing any approved speaker identity must be rejected."""
    incomplete = {"Advait": np.zeros(192, dtype=np.float32)}
    bad_pkl = tmp_path / "incomplete.pkl"
    with open(bad_pkl, "wb") as f:
        pickle.dump(incomplete, f)

    with pytest.raises(SeederValidationError, match="missing 9 approved speaker key"):
        load_and_validate_profiles(bad_pkl)


def test_embedding_wrong_dimension_rejected(synthetic_profiles, tmp_path):
    """Embeddings that do not have exactly 192 dimensions must be rejected."""
    bad_profiles = dict(synthetic_profiles["profiles"])
    bad_profiles["Advait"] = np.ones(191, dtype=np.float32)  # 191 instead of 192
    bad_pkl = tmp_path / "bad_dim.pkl"
    with open(bad_pkl, "wb") as f:
        pickle.dump(bad_profiles, f)

    with pytest.raises(SeederValidationError, match="Biometric validation failed for approved speaker 'Advait'"):
        load_and_validate_profiles(bad_pkl)


def test_embedding_nan_rejected(synthetic_profiles, tmp_path):
    """Embeddings containing NaN must be rejected."""
    bad_profiles = dict(synthetic_profiles["profiles"])
    bad_vec = bad_profiles["Zubair"].copy()
    bad_vec[10] = np.nan
    bad_profiles["Zubair"] = bad_vec
    bad_pkl = tmp_path / "nan.pkl"
    with open(bad_pkl, "wb") as f:
        pickle.dump(bad_profiles, f)

    with pytest.raises(SeederValidationError, match="Advait|Zubair"):
        load_and_validate_profiles(bad_pkl)


def test_embedding_inf_rejected(synthetic_profiles, tmp_path):
    """Embeddings containing Infinity must be rejected."""
    bad_profiles = dict(synthetic_profiles["profiles"])
    bad_vec = bad_profiles["Omar"].copy()
    bad_vec[5] = np.inf
    bad_profiles["Omar"] = bad_vec
    bad_pkl = tmp_path / "inf.pkl"
    with open(bad_pkl, "wb") as f:
        pickle.dump(bad_profiles, f)

    with pytest.raises(SeederValidationError, match="approved speaker 'Omar'"):
        load_and_validate_profiles(bad_pkl)


# ─── 2. Seeding & Idempotency Tests ────────────────────────────────────────────

def test_successful_seeding_temporary_database(test_db, synthetic_profiles):
    """Verify end-to-end atomic seeding of all approved speakers into database."""
    result = run_seed_speakers(
        profiles_path=synthetic_profiles["path"],
        dry_run=False,
        database_url=test_db["url"],
    )

    assert result.total_approved == 10
    assert result.insert_count == 10
    assert result.skip_count == 0
    assert result.dry_run is False

    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        assert repo.count() == 10

        # Check Advait (sentence-disjoint, reference_count=21)
        advait = repo.get_by_speaker_id("Advait")
        assert advait is not None
        assert advait.sample_count == 21
        assert advait.status == "active"
        assert advait.embedding_dim == 192
        advait_vec = repo.get_embedding("Advait")
        assert advait_vec is not None
        assert np.allclose(advait_vec, synthetic_profiles["profiles"]["Advait"], rtol=1e-5, atol=1e-6)

        # Check Zubair (standard enrollment, sample_count=5)
        zubair = repo.get_by_speaker_id("Zubair")
        assert zubair is not None
        assert zubair.sample_count == 5
        assert zubair.status == "active"
        zubair_vec = repo.get_embedding("Zubair")
        assert np.allclose(zubair_vec, synthetic_profiles["profiles"]["Zubair"], rtol=1e-5, atol=1e-6)

        # Excluded identities must not exist
        assert repo.get_by_speaker_id("abc") is None
        assert repo.get_by_speaker_id("maam") is None
    finally:
        session.close()


def test_seeder_rerun_idempotency(test_db, synthetic_profiles):
    """Rerunning the seeder must skip identical existing records and create zero duplicates."""
    res1 = run_seed_speakers(
        profiles_path=synthetic_profiles["path"],
        dry_run=False,
        database_url=test_db["url"],
    )
    assert res1.insert_count == 10
    assert res1.skip_count == 0

    # Second run
    res2 = run_seed_speakers(
        profiles_path=synthetic_profiles["path"],
        dry_run=False,
        database_url=test_db["url"],
    )
    assert res2.insert_count == 0
    assert res2.skip_count == 10
    assert res2.dry_run is False

    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        assert repo.count() == 10
    finally:
        session.close()


def test_dry_run_makes_no_persistent_changes(test_db, synthetic_profiles):
    """Dry run mode must validate profiles and report actions without modifying database."""
    res = run_seed_speakers(
        profiles_path=synthetic_profiles["path"],
        dry_run=True,
        database_url=test_db["url"],
    )
    assert res.dry_run is True
    assert res.insert_count == 10
    assert res.skip_count == 0

    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        assert repo.count() == 0
    finally:
        session.close()


# ─── 3. Conflict & Atomicity Tests ─────────────────────────────────────────────

def test_conflicting_existing_embedding_aborts(test_db, synthetic_profiles):
    """A conflicting existing embedding must abort the entire seeding transaction."""
    # Pre-seed one speaker with a completely different embedding
    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        different_vec = np.zeros(192, dtype=np.float32)
        repo.create(
            speaker_id="Zubair",
            full_name="Zubair",
            status="active",
            sample_count=5,
            embedding=different_vec,
        )
        session.commit()
    finally:
        session.close()

    # Attempt seeder run — should detect conflict on Zubair and abort
    with pytest.raises(SeederConflictError, match="Conflicting existing speaker record"):
        run_seed_speakers(
            profiles_path=synthetic_profiles["path"],
            dry_run=False,
            database_url=test_db["url"],
        )

    # Verify atomic rollback: Zubair has original embedding, no other speakers added
    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        assert repo.count() == 1
        zubair = repo.get_by_speaker_id("Zubair")
        assert zubair is not None
        zubair_vec = repo.get_embedding("Zubair")
        assert np.allclose(zubair_vec, np.zeros(192, dtype=np.float32))
        assert repo.get_by_speaker_id("Advait") is None
    finally:
        session.close()


def test_conflicting_existing_status_aborts(test_db, synthetic_profiles):
    """An existing record with suspended/revoked status must abort the seeding transaction."""
    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        repo.create(
            speaker_id="Advait",
            full_name="Advait",
            status="suspended",
            sample_count=21,
            embedding=synthetic_profiles["profiles"]["Advait"],
        )
        session.commit()
    finally:
        session.close()

    with pytest.raises(SeederConflictError, match="Advait"):
        run_seed_speakers(
            profiles_path=synthetic_profiles["path"],
            dry_run=False,
            database_url=test_db["url"],
        )


def test_unrelated_speaker_records_remain_unchanged(test_db, synthetic_profiles):
    """Unrelated speaker records outside the approved list must not be altered or deleted."""
    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        repo.create(
            speaker_id="ExternalPartner",
            full_name="External Partner",
            status="active",
            sample_count=10,
        )
        session.commit()
    finally:
        session.close()

    res = run_seed_speakers(
        profiles_path=synthetic_profiles["path"],
        dry_run=False,
        database_url=test_db["url"],
    )
    assert res.insert_count == 10

    session = test_db["session_factory"]()
    try:
        repo = SpeakerRepository(session)
        assert repo.count() == 11
        partner = repo.get_by_speaker_id("ExternalPartner")
        assert partner is not None
        assert partner.full_name == "External Partner"
    finally:
        session.close()


def test_atomic_rollback_when_insert_fails_midway(test_db, synthetic_profiles):
    """If an insert fails midway through seeding, all changes must be rolled back."""
    session = test_db["session_factory"]()
    try:
        validated = load_and_validate_profiles(synthetic_profiles["path"])

        # Patch SpeakerRepository.create to raise on the 4th speaker
        call_count = 0
        original_create = SpeakerRepository.create

        def failing_create(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 4:
                raise RuntimeError("Simulated transient database error")
            return original_create(self, *args, **kwargs)

        with patch.object(SpeakerRepository, "create", failing_create):
            with pytest.raises(RuntimeError, match="Simulated transient database error"):
                try:
                    seed_speakers(session, validated, dry_run=False)
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        # Confirm rollback: zero speakers persisted
        repo = SpeakerRepository(session)
        assert repo.count() == 0
    finally:
        session.close()


def test_no_firebase_mappings_created(test_db, synthetic_profiles):
    """Database seeder must not create any UserSpeakerMapping records."""
    run_seed_speakers(
        profiles_path=synthetic_profiles["path"],
        dry_run=False,
        database_url=test_db["url"],
    )

    session = test_db["session_factory"]()
    try:
        mappings_count = session.scalar(select(UserSpeakerMapping))
        assert mappings_count is None
    finally:
        session.close()


# ─── 4. Database Readiness & CLI Tests ─────────────────────────────────────────

def test_database_missing_speakers_table_fails_closed(tmp_path):
    """An unmigrated database missing the speakers table must fail closed with instructions."""
    raw_db = tmp_path / "unmigrated.db"
    db_url = f"sqlite:///{raw_db}"
    engine = create_engine(db_url)

    with pytest.raises(RuntimeError, match="missing the required 'speakers' table"):
        check_database_readiness(engine, "sqlite:///masked.db")


def test_cli_help_and_dry_run(test_db, synthetic_profiles, capsys):
    """Verify CLI argument handling, help output, and dry-run execution."""
    # Test --help
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0

    # Test --dry-run CLI invocation
    code = main([
        "--dry-run",
        "--db-url", test_db["url"],
        "--profiles-path", str(synthetic_profiles["path"]),
    ])
    assert code == 0
    captured = capsys.readouterr().out
    assert "DRY RUN" in captured
    assert "To insert (10)" in captured

    # Test live execution CLI invocation
    code = main([
        "--db-url", test_db["url"],
        "--profiles-path", str(synthetic_profiles["path"]),
    ])
    assert code == 0
    captured = capsys.readouterr().out
    assert "Successfully seeded 10 speaker record(s)" in captured

    # Test second run (idempotent skip)
    code = main([
        "--db-url", test_db["url"],
        "--profiles-path", str(synthetic_profiles["path"]),
    ])
    assert code == 0
    captured = capsys.readouterr().out
    assert "To skip (10)" in captured
