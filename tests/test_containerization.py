"""
tests/test_containerization.py — Container Configuration and Security Invariants Test Suite.

Verifies:
1. Dockerfile presence, non-root user enforcement, ffmpeg installation, health check, and entrypoint.
2. .dockerignore exclusion rules preventing leakage of credentials, audio datasets, databases, and local symlinks.
3. Production dependency specifications in requirements.txt (including firebase-admin).
4. Model cache warm-up script structure and importability.
"""

from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_contains_production_dependencies():
    """Verify requirements.txt includes all required production runtime dependencies."""
    req_file = REPO_ROOT / "requirements.txt"
    assert req_file.exists(), "requirements.txt must exist"
    content = req_file.read_text()

    required_packages = [
        "torch",
        "speechbrain",
        "vosk",
        "soundfile",
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "alembic",
        "psycopg",
        "firebase-admin",
    ]
    for pkg in required_packages:
        assert re.search(rf"^{pkg}(\[.*\])?([><=~].*)?$", content, re.MULTILINE), (
            f"Package '{pkg}' must be specified in requirements.txt"
        )


def test_dockerfile_security_and_runtime_conventions():
    """Verify Dockerfile enforces non-root execution, ffmpeg, model warmup, and health probes."""
    dockerfile = REPO_ROOT / "Dockerfile"
    assert dockerfile.exists(), "Dockerfile must exist"
    content = dockerfile.read_text()

    # Base image
    assert "FROM python:3.11-slim" in content, "Dockerfile should use python:3.11-slim base"

    # Audio preprocessing OS dependencies
    assert "ffmpeg" in content, "Dockerfile must install ffmpeg for audio normalization"
    assert "libsndfile1" in content, "Dockerfile must install libsndfile1 for soundfile"
    assert "curl" in content, "Dockerfile must install curl for container health checks"

    # Non-root user creation and execution
    assert "useradd" in content, "Dockerfile must create an unprivileged user"
    assert "USER voicelock" in content, "Dockerfile must switch to unprivileged user voicelock"

    # Model cache pre-warming and non-root permission isolation
    assert "HF_HOME=/home/voicelock/.cache/huggingface" in content, (
        "Dockerfile must configure HF_HOME under unprivileged user home"
    )
    assert content.index("USER voicelock") < content.index("warmup_models.py"), (
        "Dockerfile must switch to USER voicelock before pre-warming models so cache files/symlinks are owned by voicelock"
    )
    assert "warmup_models.py" in content, "Dockerfile must execute model pre-warming during build"

    # Health check matching GET /
    assert "HEALTHCHECK" in content, "Dockerfile must define a container HEALTHCHECK"
    assert "http://localhost:8000/" in content, "HEALTHCHECK probe must query existing discovery endpoint"

    # Production entrypoint
    assert "uvicorn" in content and "app.main:app" in content, (
        "Dockerfile CMD must run uvicorn with app.main:app"
    )


def test_dockerignore_security_exclusions():
    """Verify .dockerignore strictly excludes credentials, datasets, audio, and developer symlinks."""
    dockerignore = REPO_ROOT / ".dockerignore"
    assert dockerignore.exists(), ".dockerignore must exist"
    content = dockerignore.read_text()
    patterns = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

    critical_exclusions = [
        ".env*",
        "firebase-credentials*.json",
        ".venv/",
        "voicelock.db",
        "dataset/",
        "processed_dataset/",
        "recordings/",
        "speaker_profiles/",
        "*.wav",
        ".model_cache/",
        "frontend/",
    ]
    for exclusion in critical_exclusions:
        assert exclusion in patterns or any(exclusion in p for p in patterns), (
            f"Critical exclusion pattern '{exclusion}' must be in .dockerignore"
        )


def test_warmup_models_script_structure():
    """Verify scripts/warmup_models.py defines warmup_all_models and imports cleanly."""
    script = REPO_ROOT / "scripts" / "warmup_models.py"
    assert script.exists(), "scripts/warmup_models.py must exist"

    import scripts.warmup_models as warmup_mod
    assert hasattr(warmup_mod, "warmup_all_models"), "warmup_models must define warmup_all_models()"
    assert callable(warmup_mod.warmup_all_models)


def test_app_lifespan_prewarms_model_and_handles_deferred_db(monkeypatch):
    """Verify FastAPI lifespan pre-warms the ML model singleton and defers cleanly if DB is uninitialized."""
    import asyncio
    from app.main import app, lifespan
    import app.services.speaker_service as ss

    classifier_prewarmed = False
    original_get_classifier = ss.get_classifier

    def mock_get_classifier():
        nonlocal classifier_prewarmed
        classifier_prewarmed = True
        return original_get_classifier()

    monkeypatch.setattr(ss, "get_classifier", mock_get_classifier)
    monkeypatch.setattr(
        "app.main.get_system",
        lambda: (_ for _ in ()).throw(RuntimeError("Simulated uninitialized database")),
    )

    async def _run():
        async with lifespan(app):
            pass

    asyncio.run(_run())
    assert classifier_prewarmed is True

