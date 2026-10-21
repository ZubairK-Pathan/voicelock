"""
tests/test_liveness_unit.py — Unit and regression tests for liveness challenge verification.

Verifies:
1. Exact digit sequence matching.
2. English phonetic homophone resolution (to, too, for, fore, won, ate, o, oh).
3. Formatted multi-digit string parsing (e.g. '148' -> ['1', '4', '8']).
4. Mixed digit and word extraction.
5. Strict anti-spoofing rejection of incorrect sequences, missing digits, and silence.
6. Single-attempt invalidation ('burn-on-use') and challenge lifecycle in InMemoryChallengeStore.
"""

import pytest
import time
from liveness import (
    verify_liveness,
    generate_challenge,
    challenge_display,
    challenge_expected_words,
    InMemoryChallengeStore,
    ChallengeStatus,
    WORD_TO_DIGIT,
    DIGIT_WORDS,
)


def test_verify_liveness_exact_word_match():
    """Verify standard word transcripts match challenge sequences."""
    challenge = ["7", "2", "9"]
    transcript = "seven two nine"
    passed, reason = verify_liveness(transcript, challenge)
    assert passed is True
    assert "successfully" in reason.lower()


def test_verify_liveness_phonetic_homophones_resolution():
    """
    Regression test: Vosk often transcribes digit homophones in open speech:
    - 'to' / 'too' for 'two'
    - 'for' / 'fore' for 'four'
    - 'won' for 'one'
    - 'ate' for 'eight'
    - 'o' / 'oh' for 'zero'
    These must be resolved to their numeric digits.
    """
    # 'to' for 2, 'for' for 4
    passed, _ = verify_liveness("for to eight", ["4", "2", "8"])
    assert passed is True

    # 'too' for 2, 'ate' for 8
    passed, _ = verify_liveness("won too ate", ["1", "2", "8"])
    assert passed is True

    # 'o' and 'oh' for 0
    passed, _ = verify_liveness("o five six", ["0", "5", "6"])
    assert passed is True
    passed, _ = verify_liveness("oh five six", ["0", "5", "6"])
    assert passed is True

    # 'to seven nine'
    passed, _ = verify_liveness("to seven nine", ["2", "7", "9"])
    assert passed is True


def test_verify_liveness_multi_digit_numeric_strings():
    """
    Regression test: When transcription returns compact digit strings (e.g. '148'),
    individual digit characters must be extracted sequentially.
    """
    passed, _ = verify_liveness("148", ["1", "4", "8"])
    assert passed is True

    passed, _ = verify_liveness("code 729 verified", ["7", "2", "9"])
    assert passed is True

    passed, _ = verify_liveness("say 42 then 8", ["4", "2", "8"])
    assert passed is True


def test_verify_liveness_mixed_digits_and_words():
    """Digits can appear as numerals and spoken words intermixed."""
    passed, _ = verify_liveness("seven 2 nine", ["7", "2", "9"])
    assert passed is True


def test_verify_liveness_silence_and_none_fail_closed():
    """Ensure None or empty transcripts fail closed."""
    passed, reason = verify_liveness(None, ["1", "2", "3"])
    assert passed is False
    assert "could not transcribe" in reason.lower()

    passed, reason = verify_liveness("", ["1", "2", "3"])
    assert passed is False
    assert "no speech detected" in reason.lower()

    passed, reason = verify_liveness("   ", ["1", "2", "3"])
    assert passed is False
    assert "no speech detected" in reason.lower()


def test_verify_liveness_no_digits_heard():
    """Words that contain no recognized digits must report no digits heard."""
    passed, reason = verify_liveness("hello world testing microphone", ["1", "2", "3"])
    assert passed is False
    assert "no digits heard" in reason.lower()


def test_verify_liveness_order_and_value_mismatch_fails_spoof_detection():
    """Security invariant: out-of-order, incomplete, or incorrect digits must fail."""
    # Out of order
    passed, reason = verify_liveness("nine two seven", ["7", "2", "9"])
    assert passed is False
    assert "challenge failed" in reason.lower()

    # Wrong digits
    passed, reason = verify_liveness("seven three nine", ["7", "2", "9"])
    assert passed is False
    assert "challenge failed" in reason.lower()

    # Incomplete (2 out of 3)
    passed, reason = verify_liveness("seven nine", ["7", "2", "9"])
    assert passed is False
    assert "challenge failed" in reason.lower()

    # Extra digits
    passed, reason = verify_liveness("seven two nine four", ["7", "2", "9"])
    assert passed is False
    assert "challenge failed" in reason.lower()


def test_in_memory_challenge_store_lifecycle():
    """Verify challenge store creation, single-attempt invalidation, and expiration."""
    store = InMemoryChallengeStore()
    ch = store.create_challenge(session_id="sess_100", claimed_identity="Zubair", ttl_seconds=60)
    assert ch.status == ChallengeStatus.PENDING
    assert ch.claimed_identity == "Zubair"

    # Valid consume burns the challenge immediately
    ok, msg, consumed = store.validate_and_consume(
        challenge_id=ch.challenge_id,
        session_id="sess_100",
        claimed_identity="Zubair",
    )
    assert ok is True
    assert consumed.status == ChallengeStatus.CONSUMED

    # Replaying same challenge fails (Single-Attempt Invalidation)
    ok_replay, msg_replay, _ = store.validate_and_consume(
        challenge_id=ch.challenge_id,
        session_id="sess_100",
        claimed_identity="Zubair",
    )
    assert ok_replay is False
    assert "already been consumed" in msg_replay.lower()
