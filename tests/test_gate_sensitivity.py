"""Unit tests for tools/gate_sensitivity.py (EX-2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import gate_sensitivity as gs  # noqa: E402


def _candidate(cid, lift, regime_pass=True, cost_pass=True):
    return {
        "candidate_id": cid,
        "pf_lift_aggregate": lift,
        "regime_non_negative": regime_pass,
        "cost_persistent_at_1pip": cost_pass,
    }


class TestEvaluateGates:
    def test_all_passing_cohort(self):
        cands = [
            _candidate("AF-CAND-0734", 0.05),
            _candidate("AF-CAND-0322", 0.05),
            _candidate("AF-CAND-0323", 0.05),
            _candidate("AF-CAND-0007", 0.05),
            _candidate("AF-CAND-0002", 0.05),
            _candidate("AF-CAND-0290", 0.05),
            _candidate("AF-CAND-0716", 0.02),
            _candidate("AF-CAND-0738", 0.02),
            _candidate("AF-CAND-0739", 0.02),
            _candidate("AF-CAND-0009", 0.02),
            _candidate("AF-CAND-0001", 0.02),
        ]
        out = gs.evaluate_gates(cands, sigma_cross=0.02, mde_point=0.04, mde_upper=0.05, effect_size_floor=0.01)
        assert out["q1_retrospective_verdict_on_1_6"] == "PRIMARY_OK"
        assert out["i1_locked_tier"] == "TIER_1_PROCEED"
        assert out["n_above_effect_size_floor"] == 11
        assert out["survivor_mean_lift"] == pytest.approx(0.05)
        assert out["fragile_mean_lift"] == pytest.approx(0.02)

    def test_q1_conditional_restricted_trigger(self):
        cands = [
            _candidate(f"AF-CAND-073{i}", 0.05) for i in range(4, 7)
        ] + [
            _candidate("AF-CAND-0322", 0.05),
            _candidate("AF-CAND-0002", 0.05),
            _candidate("AF-CAND-0290", 0.05),
            # Fragiles: mean = -0.025, only -1.25*sigma_cross from zero (sigma=0.02)
            _candidate("AF-CAND-0716", -0.03),
            _candidate("AF-CAND-0738", -0.02),
            _candidate("AF-CAND-0739", -0.025),
            _candidate("AF-CAND-0009", -0.025),
            _candidate("AF-CAND-0001", -0.025),
        ]
        out = gs.evaluate_gates(cands, sigma_cross=0.02, mde_point=0.04, mde_upper=0.05, effect_size_floor=0.01)
        assert out["q1_retrospective_verdict_on_1_6"] == "CONDITIONAL_RESTRICTED"

    def test_q1_nogo_trigger(self):
        cands = [
            _candidate(c, 0.05) for c in
            ["AF-CAND-0734", "AF-CAND-0322", "AF-CAND-0323",
             "AF-CAND-0007", "AF-CAND-0002", "AF-CAND-0290"]
        ] + [
            # mean = -0.06 = -3*sigma_cross with all 5 negative
            _candidate("AF-CAND-0716", -0.06),
            _candidate("AF-CAND-0738", -0.06),
            _candidate("AF-CAND-0739", -0.06),
            _candidate("AF-CAND-0009", -0.06),
            _candidate("AF-CAND-0001", -0.06),
        ]
        out = gs.evaluate_gates(cands, sigma_cross=0.02, mde_point=0.04, mde_upper=0.05, effect_size_floor=0.01)
        assert out["q1_retrospective_verdict_on_1_6"] == "NO_GO"

    def test_q1_breadth_required_for_nogo(self):
        # Mean is < -2*sigma_cross but only 2/5 negative (1 huge negative dragging mean)
        cands = [
            _candidate(c, 0.05) for c in
            ["AF-CAND-0734", "AF-CAND-0322", "AF-CAND-0323",
             "AF-CAND-0007", "AF-CAND-0002", "AF-CAND-0290"]
        ] + [
            _candidate("AF-CAND-0716", -0.30),
            _candidate("AF-CAND-0738", -0.05),
            _candidate("AF-CAND-0739", 0.01),
            _candidate("AF-CAND-0009", 0.01),
            _candidate("AF-CAND-0001", 0.01),
        ]
        out = gs.evaluate_gates(cands, sigma_cross=0.02, mde_point=0.04, mde_upper=0.05, effect_size_floor=0.01)
        # mean = -0.064 < -0.04 (-2sigma) but only 2/5 negative -> CONDITIONAL not NO_GO
        assert out["q1_retrospective_verdict_on_1_6"] == "CONDITIONAL_RESTRICTED"


class TestI1TierBoundaries:
    @pytest.mark.parametrize("upper,expected", [
        (0.05, "TIER_1_PROCEED"),
        (0.10, "TIER_1_PROCEED"),
        (0.12, "TIER_2_BORDERLINE"),
        (0.15, "TIER_2_BORDERLINE"),
        (0.16, "TIER_3_DO_NOT_RUN"),
    ])
    def test_i1_tier_via_evaluate(self, upper, expected):
        cands = [_candidate("AF-CAND-0734", 0.05)]
        out = gs.evaluate_gates(cands, sigma_cross=0.02, mde_point=0.04, mde_upper=upper, effect_size_floor=0.01)
        assert out["i1_locked_tier"] == expected


class TestRenderDeterminism:
    def test_render_excluding_timestamp_is_stable(self):
        cands = [_candidate(c, 0.05) for c in
                 ["AF-CAND-0734", "AF-CAND-0322", "AF-CAND-0323",
                  "AF-CAND-0007", "AF-CAND-0002", "AF-CAND-0290"]]
        gates = gs.evaluate_gates(cands, sigma_cross=0.02, mde_point=0.04, mde_upper=0.05, effect_size_floor=0.01)
        kwargs = dict(
            run_id="TEST", dataset_sha="a"*64, report_sha="b"*64,
            sigma_cross=0.02, mde_point=0.04, mde_upper=0.05,
            effect_size_floor=0.01, gates=gates,
        )
        md1 = gs.render_report(runtime_utc="2026-04-20T00:00:00Z", **kwargs)
        md2 = gs.render_report(runtime_utc="2099-12-31T23:59:59Z", **kwargs)
        s1 = "\n".join(line for line in md1.splitlines() if "Generated UTC" not in line)
        s2 = "\n".join(line for line in md2.splitlines() if "Generated UTC" not in line)
        assert s1 == s2
