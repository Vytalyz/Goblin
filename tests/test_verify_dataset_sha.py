"""Tests for tools/verify_dataset_sha.py (ML-1.7)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.verify_dataset_sha import (  # noqa: E402
    DEFAULT_DATASET,
    PINNED_SHA256,
    compute_sha256,
    main,
    verify,
)


def test_compute_sha256_matches_expected(tmp_path: Path) -> None:
    payload = b"hello goblin"
    p = tmp_path / "x.bin"
    p.write_bytes(payload)
    assert compute_sha256(p) == hashlib.sha256(payload).hexdigest()


def test_verify_passes_when_sha_matches(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    expected = hashlib.sha256(b"abc").hexdigest()
    assert verify(p, expected) == expected


def test_verify_raises_on_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    with pytest.raises(ValueError, match="SHA mismatch"):
        verify(p, "0" * 64)


def test_verify_is_case_insensitive(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    expected = hashlib.sha256(b"abc").hexdigest().upper()
    assert verify(p, expected).lower() == expected.lower()


def test_main_reports_missing_dataset(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--path", str(tmp_path / "absent.parquet"), "--expected", "0" * 64])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_main_reports_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "x.parquet"
    p.write_bytes(b"abc")
    rc = main(["--path", str(p), "--expected", "0" * 64])
    assert rc == 1
    assert "SHA mismatch" in capsys.readouterr().err


def test_main_passes_for_correct_sha(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "x.parquet"
    p.write_bytes(b"abc")
    expected = hashlib.sha256(b"abc").hexdigest()
    rc = main(["--path", str(p), "--expected", expected])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_canonical_dataset_matches_pin() -> None:
    """The committed canonical research dataset must match the pinned sha."""
    if not DEFAULT_DATASET.exists():
        pytest.skip("canonical dataset not present in checkout")
    assert compute_sha256(DEFAULT_DATASET) == PINNED_SHA256
