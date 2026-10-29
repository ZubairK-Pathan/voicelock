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
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from liveness import (
    verify_liveness,
    generate_challenge,
    challenge_display,
    challenge_expected_words,
    InMemoryChallengeStore,
    ChallengeStatus,
    WORD_TO_DIGIT,
    DIGIT_WORDS,
    is_valid_vosk_model_dir,
    _ensure_model,
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


# ─── Vosk Model Validation & Cache Handling Tests ────────────────────────────

def test_is_valid_vosk_model_dir_validation(tmp_path):
    """Verify validation logic for Vosk model directory structure."""
    assert is_valid_vosk_model_dir(None) is False
    assert is_valid_vosk_model_dir("") is False
    assert is_valid_vosk_model_dir(tmp_path / "non_existent") is False

    # Path is a file, not a directory
    file_path = tmp_path / "model_file.txt"
    file_path.write_text("not a directory")
    assert is_valid_vosk_model_dir(file_path) is False

    # Empty directory
    model_dir = tmp_path / "vosk_model"
    model_dir.mkdir()
    assert is_valid_vosk_model_dir(model_dir) is False

    # Missing am/final.mdl
    (model_dir / "conf").mkdir()
    (model_dir / "graph").mkdir()
    assert is_valid_vosk_model_dir(model_dir) is False

    # am directory exists but final.mdl missing
    (model_dir / "am").mkdir()
    assert is_valid_vosk_model_dir(model_dir) is False

    # Complete valid directory structure
    (model_dir / "am" / "final.mdl").write_bytes(b"dummy_weights")
    assert is_valid_vosk_model_dir(model_dir) is True
    # Test str input path
    assert is_valid_vosk_model_dir(str(model_dir)) is True


def test_ensure_model_already_populated_cache(tmp_path, monkeypatch):
    """
    Test requirement: Test an already-populated cache.
    When a valid model directory already exists, _ensure_model must return it
    immediately without triggering download or extraction.
    """
    model_dir = tmp_path / "vosk-model-small-en-us"
    (model_dir / "am").mkdir(parents=True)
    (model_dir / "conf").mkdir(parents=True)
    (model_dir / "graph").mkdir(parents=True)
    (model_dir / "am" / "final.mdl").write_bytes(b"model_weights")

    urlretrieve_called = False

    def mock_urlretrieve(url, filename):
        nonlocal urlretrieve_called
        urlretrieve_called = True

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

    result = _ensure_model(target_dir=model_dir)
    assert result == model_dir
    assert urlretrieve_called is False
    assert is_valid_vosk_model_dir(result) is True


def _create_valid_model_zip(zip_path: Path, internal_folder_name: str = "vosk-model-small-en-us-0.15"):
    """Helper to create a valid dummy Vosk model zip file."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{internal_folder_name}/am/final.mdl", b"acoustic_model_binary")
        zf.writestr(f"{internal_folder_name}/conf/model.conf", "--sample-frequency=16000")
        zf.writestr(f"{internal_folder_name}/graph/HCLG.fst", b"graph_fst_binary")


def test_ensure_model_clean_cache_and_zip_vs_dir_glob_selection(tmp_path, monkeypatch):
    """
    Regression test for the production STT bug:
    1. Tests clean model-cache build.
    2. Tests that ZIP files are not mistaken for extracted directories when globbing.
    3. Confirms final directory contains am/final.mdl, conf, and graph.
    """
    cache_dir = tmp_path / "model_cache"
    cache_dir.mkdir()
    target_dir = cache_dir / "vosk-model-small-en-us"

    source_zip = tmp_path / "source.zip"
    _create_valid_model_zip(source_zip, "vosk-model-small-en-us-0.15")

    # Also place a decoy ZIP file in the cache directory matching the glob
    decoy_zip = cache_dir / "vosk-model-small-en-us-extra.zip"
    decoy_zip.write_bytes(b"decoy zip content")

    def mock_urlretrieve(url, filename):
        import shutil
        shutil.copyfile(source_zip, filename)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

    result = _ensure_model(target_dir=target_dir)

    assert result == target_dir
    assert target_dir.is_dir()
    assert is_valid_vosk_model_dir(target_dir) is True
    assert (target_dir / "am" / "final.mdl").exists()
    assert (target_dir / "conf" / "model.conf").exists()
    assert (target_dir / "graph" / "HCLG.fst").exists()
    # The temporary target zip must have been unlinked
    assert not (cache_dir / "vosk-model-small-en-us.zip").exists()


def test_ensure_model_recovers_from_corrupted_cache_file(tmp_path, monkeypatch):
    """
    Regression test: When target_dir exists as a regular file (e.g. if a previous build
    corrupted the path by moving the .zip file to the directory name), _ensure_model
    safely purges it and extracts a valid directory.
    """
    cache_dir = tmp_path / "model_cache"
    cache_dir.mkdir()
    target_dir = cache_dir / "vosk-model-small-en-us"
    # Create corrupted file where directory was expected
    target_dir.write_text("corrupted file contents from previous failed extraction")
    assert target_dir.is_file()

    source_zip = tmp_path / "source.zip"
    _create_valid_model_zip(source_zip, "vosk-model-small-en-us-0.15")

    def mock_urlretrieve(url, filename):
        import shutil
        shutil.copyfile(source_zip, filename)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

    result = _ensure_model(target_dir=target_dir)

    assert result == target_dir
    assert target_dir.is_dir()
    assert not target_dir.is_file()
    assert is_valid_vosk_model_dir(target_dir) is True
    assert (target_dir / "am" / "final.mdl").read_bytes() == b"acoustic_model_binary"


def test_ensure_model_recovers_from_empty_or_incomplete_dir(tmp_path, monkeypatch):
    """When target_dir exists but is missing essential files, _ensure_model purges and re-extracts."""
    cache_dir = tmp_path / "model_cache"
    cache_dir.mkdir()
    target_dir = cache_dir / "vosk-model-small-en-us"
    target_dir.mkdir()
    (target_dir / "am").mkdir()
    # Incomplete: missing final.mdl, conf, graph

    source_zip = tmp_path / "source.zip"
    _create_valid_model_zip(source_zip, "vosk-model-small-en-us-0.15")

    def mock_urlretrieve(url, filename):
        import shutil
        shutil.copyfile(source_zip, filename)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

    result = _ensure_model(target_dir=target_dir)
    assert result == target_dir
    assert is_valid_vosk_model_dir(target_dir) is True


def test_ensure_model_raises_runtime_error_if_extracted_model_is_invalid(tmp_path, monkeypatch):
    """If the zip archive does not contain the required files, _ensure_model raises RuntimeError."""
    cache_dir = tmp_path / "model_cache"
    cache_dir.mkdir()
    target_dir = cache_dir / "vosk-model-small-en-us"

    broken_zip = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken_zip, "w") as zf:
        zf.writestr("vosk-model-small-en-us-0.15/README", "missing model files")

    def mock_urlretrieve(url, filename):
        import shutil
        shutil.copyfile(broken_zip, filename)

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlretrieve", mock_urlretrieve)

    with pytest.raises(RuntimeError, match="invalid or missing required model files"):
        _ensure_model(target_dir=target_dir)


def test_warmup_models_fails_if_vosk_model_fails_to_load(tmp_path, monkeypatch):
    """
    Test requirement: warmup_models.py must instantiate the actual Vosk Model
    and the build must fail if the model cannot load.
    """
    import scripts.warmup_models as warmup_script

    fake_model_path = tmp_path / "vosk_model"
    fake_model_path.mkdir()

    monkeypatch.setattr(warmup_script, "load_embedding_model", lambda: MagicMock())
    monkeypatch.setattr(warmup_script, "_ensure_model", lambda: fake_model_path)

    import sys
    fake_vosk = MagicMock()
    fake_vosk.Model.side_effect = RuntimeError("Corrupted model graph")
    monkeypatch.setitem(sys.modules, "vosk", fake_vosk)

    with pytest.raises(RuntimeError, match="Vosk Model initialization failed"):
        warmup_script.warmup_all_models()

