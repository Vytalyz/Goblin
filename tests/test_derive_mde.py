"""
Unit tests for tools/derive_mde.py (EX-1).

Coverage targets per Revision 4.2-final §15.12 Layer 1 + Layer 3:
  - σ_cross computation correctness (5 fixture-based variants)
  - MDE derivation: point estimate + bootstrap CI (4 tests including
    conservative-tier-on-upper-bound rule from I1)
  - Bootstrap reproducibility under pinned RNG seed
  - R4-3 Constraint 4 dataset SHA-mismatch refusal (G6)
  - Manifest determinism (Layer 3)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import derive_mde  # noqa: E402


# ---------------------------------------------------------------------------
# σ_cross unit tests (5 fixture-based variants).
# ---------------------------------------------------------------------------
class TestSigmaCross:
    def test_sigma_cross_known_values(self):
        # Mean lift values chosen so stdev (ddof=1) = exactly 0.05.
        # For [0.0, 0.1] → mean=0.05, ddof=1 stdev = sqrt(2*(0.05)^2/(2-1)) = 0.0707...
        # Use [0.0, 0.05, 0.10] → ddof=1 stdev = 0.05 exactly.
        means = np.array([0.0, 0.05, 0.10])
        result = derive_mde.sigma_cross(means)
        assert result == pytest.approx(0.05, abs=1e-12)

    def test_sigma_cross_all_equal_returns_zero(self):
        means = np.array([0.05, 0.05, 0.05, 0.05])
        assert derive_mde.sigma_cross(means) == pytest.approx(0.0, abs=1e-12)

    def test_sigma_cross_single_candidate_raises(self):
        with pytest.raises(ValueError, match="at least 2 candidates"):
            derive_mde.sigma_cross(np.array([0.05]))

    def test_sigma_cross_large_spread(self):
        means = np.array([-1.0, 0.0, 1.0])
        # ddof=1 stdev of [-1, 0, 1] = 1.0
        assert derive_mde.sigma_cross(means) == pytest.approx(1.0, abs=1e-12)

    def test_sigma_cross_order_invariant(self):
        # Locked definition: rearranging seed/fold or candidate order doesn't
        # change σ_cross (per §15.12 Layer 4 property test, simplified).
        a = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
        b = np.array([0.05, 0.03, 0.01, 0.04, 0.02])
        assert derive_mde.sigma_cross(a) == pytest.approx(derive_mde.sigma_cross(b))


# ---------------------------------------------------------------------------
# Per-candidate mean lift extraction (handles fold_pf_lift OR derived).
# ---------------------------------------------------------------------------
class TestPerCandidateMeanLift:
    def test_uses_fold_pf_lift_when_present(self):
        candidates = [
            {
                "candidate_id": "AF-CAND-XYZ",
                "fold_pf_lift": [0.04, 0.05, 0.06],
                "fold_xgb_pf": [99.0, 99.0, 99.0],  # ignored
                "fold_rule_pf": [0.0, 0.0, 0.0],  # ignored
            }
        ]
        means = derive_mde.per_candidate_mean_lift(candidates)
        assert means == pytest.approx(np.array([0.05]))

    def test_derives_lift_from_xgb_minus_rule_when_missing(self):
        candidates = [
            {
                "candidate_id": "AF-CAND-XYZ",
                "fold_xgb_pf": [1.10, 1.05, 1.00],
                "fold_rule_pf": [1.00, 1.00, 1.00],
            }
        ]
        means = derive_mde.per_candidate_mean_lift(candidates)
        # mean of [0.10, 0.05, 0.00] = 0.05
        assert means == pytest.approx(np.array([0.05]))


# ---------------------------------------------------------------------------
# MDE derivation tests (4 tests including I1 tier rule).
# ---------------------------------------------------------------------------
class TestDeriveMDE:
    def test_mde_zero_sigma_returns_zero(self):
        assert derive_mde.derive_mde(0.0) == pytest.approx(0.0, abs=1e-12)

    def test_mde_scales_linearly_with_sigma(self):
        m1 = derive_mde.derive_mde(0.01)
        m2 = derive_mde.derive_mde(0.02)
        assert m2 == pytest.approx(2.0 * m1, rel=1e-9)

    def test_mde_decreases_with_more_candidates(self):
        small_n = derive_mde.derive_mde(0.05, n=6)
        large_n = derive_mde.derive_mde(0.05, n=20)
        assert large_n < small_n

    def test_mde_n_lt_2_raises(self):
        with pytest.raises(ValueError, match="n >= 2"):
            derive_mde.derive_mde(0.05, n=1)


# ---------------------------------------------------------------------------
# I1 tier classification.
# ---------------------------------------------------------------------------
class TestI1Tier:
    @pytest.mark.parametrize(
        "mde,expected",
        [
            (0.05, "TIER_1_PROCEED"),
            (0.10, "TIER_1_PROCEED"),
            (0.10001, "TIER_2_BORDERLINE"),
            (0.15, "TIER_2_BORDERLINE"),
            (0.15001, "TIER_3_DO_NOT_RUN"),
            (0.50, "TIER_3_DO_NOT_RUN"),
        ],
    )
    def test_i1_tier_boundaries(self, mde, expected):
        assert derive_mde.i1_tier(mde) == expected


# ---------------------------------------------------------------------------
# Bootstrap reproducibility (Layer 3 — determinism).
# ---------------------------------------------------------------------------
class TestBootstrapReproducibility:
    def test_bootstrap_bit_identical_at_fixed_seed(self):
        means = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        ci1 = derive_mde.bootstrap_sigma_cross_ci(means, n_resamples=1000, rng_seed=42)
        ci2 = derive_mde.bootstrap_sigma_cross_ci(means, n_resamples=1000, rng_seed=42)
        assert ci1 == ci2

    def test_bootstrap_different_seed_different_output(self):
        means = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        ci1 = derive_mde.bootstrap_sigma_cross_ci(means, n_resamples=1000, rng_seed=42)
        ci2 = derive_mde.bootstrap_sigma_cross_ci(means, n_resamples=1000, rng_seed=43)
        assert ci1 != ci2

    def test_bootstrap_ci_brackets_point_estimate(self):
        means = np.array([0.0, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12])
        point = derive_mde.sigma_cross(means)
        ci_low, ci_high = derive_mde.bootstrap_sigma_cross_ci(
            means, n_resamples=2000, rng_seed=20260420
        )
        assert ci_low <= point <= ci_high


# ---------------------------------------------------------------------------
# R4-3 Constraint 4: dataset SHA-mismatch refusal (G6).
# ---------------------------------------------------------------------------
class TestDatasetShaMismatchRefusal:
    def test_main_raises_on_sha_mismatch(self, tmp_path, monkeypatch):
        # Point the script at a tmp dataset whose SHA will not match the locked one.
        bogus_dataset = tmp_path / "fake.parquet"
        bogus_dataset.write_bytes(b"this is not the real dataset")
        bogus_sha = hashlib.sha256(b"this is not the real dataset").hexdigest()

        monkeypatch.setattr(derive_mde, "read_locked_dataset_sha", lambda: "0" * 64)
        monkeypatch.setattr(
            derive_mde,
            "_load_toml",
            lambda _path: {
                "ml_baseline_comparison": {
                    "dataset_sha": "0" * 64,
                    "dataset_path": str(bogus_dataset.relative_to(tmp_path)),
                    "report_path": "ignored",
                }
            },
        )
        monkeypatch.setattr(derive_mde, "REPO_ROOT", tmp_path)

        with pytest.raises(derive_mde.DatasetSHAMismatchError) as exc_info:
            derive_mde.main([])
        msg = str(exc_info.value)
        assert "Dataset SHA mismatch" in msg
        assert "0000000" in msg
        assert bogus_sha[:7] in msg

    def test_main_refuses_empty_locked_sha_without_flag(self, tmp_path, monkeypatch):
        ds = tmp_path / "fake.parquet"
        ds.write_bytes(b"x")
        monkeypatch.setattr(
            derive_mde,
            "_load_toml",
            lambda _path: {
                "ml_baseline_comparison": {
                    "dataset_sha": "",
                    "dataset_path": str(ds.relative_to(tmp_path)),
                    "report_path": "ignored",
                }
            },
        )
        monkeypatch.setattr(derive_mde, "read_locked_dataset_sha", lambda: "")
        monkeypatch.setattr(derive_mde, "REPO_ROOT", tmp_path)
        rc = derive_mde.main([])
        assert rc == 3


# ---------------------------------------------------------------------------
# Manifest determinism (Layer 3).
# ---------------------------------------------------------------------------
class TestManifestDeterminism:
    def test_manifest_payload_excluding_timestamp_is_stable(self):
        means = np.array([0.04, 0.05, 0.06])
        kwargs = dict(
            dataset_sha="a" * 64,
            report_sha="b" * 64,
            per_candidate_means=means,
            sigma_point=0.05,
            sigma_ci_low=0.04,
            sigma_ci_high=0.06,
            mde_point=0.08,
            mde_at_upper_ci=0.09,
            code_sha="c" * 64,
            library_versions={"numpy": "1.0", "scipy": "1.0", "python": "3.13"},
        )
        p1 = derive_mde.manifest_payload(runtime_utc="2026-04-20T00:00:00Z", **kwargs)
        p2 = derive_mde.manifest_payload(runtime_utc="2099-12-31T23:59:59Z", **kwargs)
        # Strip timestamp; rest must be byte-identical when serialized.
        p1.pop("runtime_utc")
        p2.pop("runtime_utc")
        s1 = json.dumps(p1, indent=2, sort_keys=True)
        s2 = json.dumps(p2, indent=2, sort_keys=True)
        assert s1 == s2

    def test_compute_file_sha256_known_value(self, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"hello")
        expected = hashlib.sha256(b"hello").hexdigest()
        assert derive_mde.compute_file_sha256(f) == expected
