"""
app/services/challenge_service.py — Challenge store interface and lifecycle service.
"""

from typing import Optional
from liveness import (
    BaseChallengeStore,
    InMemoryChallengeStore,
    LivenessChallenge,
    ChallengeStatus,
    default_challenge_store,
    generate_challenge,
    challenge_display,
    challenge_expected_words,
    run_liveness_check,
)


def get_challenge_store() -> BaseChallengeStore:
    """Return the active challenge store singleton."""
    return default_challenge_store
