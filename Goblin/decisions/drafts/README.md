# EX-9: Phase 2.0 Pre-Registration HITL Approval Gate

**Status: PENDING OWNER APPROVAL**

This directory holds three drafted decision-log entries that pre-register
the Phase 2.0 ML scope, statistical bands, and architecture-fence amendment
**before** the sealed Phase 2 holdout is ever decrypted. Per
Revision 4.2-final §15.9, owner approval is required before these are
appended to `Goblin/decisions/ml_decisions.jsonl`.

## Drafts (review in this order)

| Draft | Purpose |
|---|---|
| `DEC-ML-2.0-CANDIDATES.draft.jsonl` | Locks the n=6 survivor primary cohort and the n=11 secondary descriptive cohort for Phase 2.0. |
| `DEC-ML-2.0-TARGET.draft.jsonl` | Locks verdict bands (target=0.10 PF, CONDITIONAL=0.055 PF, NO_GO else), Q1 fragile rule, BCa moving-block bootstrap parameters, Bonferroni family, and the R4-11 midpoint+trigger prediction scaffold. |
| `DEC-ML-1.6b-A1-AUTHORIZATION.draft.jsonl` | Amendment A1: sequential 1D-CNN features are excluded from the Phase 2 primary endpoint. |

## Pre-flight Checks Already Run

- [x] EX-1 σ_cross + MDE numbers locked: `[ml_p2]` block in `config/eval_gates.toml`.
- [x] EX-2 gate sensitivity report SHA `f1c9adf801fe1e9f992df111c03612fb7b90cc3de06a24df03004da53ae7402c`
      shows Q1 retrospective verdict on 1.6 = `PRIMARY_OK`. Gates were not tuned to outcome.
- [x] EX-3 predictions log infrastructure ready (empty `predictions.jsonl`,
      validator, 3 CI jobs, CODEOWNERS).
- [x] EX-4 holdout ceremony tool deployed (hard cap=2, abort accounting, key-outside-repo).
- [x] EX-5 `[ml-p2]` extra pinned, torch determinism test in place (skip-without-torch locally).
- [x] EX-6 regime thresholds frozen: `abs_momentum_12_median = 1.9000000000`, `volatility_20_median = 0.0000741639`.
- [x] EX-7 grandfather frozenset hardened with module + test assertions.
- [x] EX-8 synthetic 4-regime data generator validated; covers all 4 regimes under EX-6 thresholds.
- [x] Full pytest sweep: **628 passing, 0 failed, 1 skipped (torch on Windows local).**
- [x] Commit SHA at draft time: `8747d4503aa5da0f32ad687a64ef478d4412e10f` (referenced in each draft).

## Owner Review Checklist

For each draft, verify:

1. **Primary cohort** (`DEC-ML-2.0-CANDIDATES`) matches the 6 survivors
   from `Goblin/reports/ml/p1_6_baseline_comparison.json` where
   `regime_non_negative AND cost_persistent_at_1pip` are both true.
2. **Verdict bands** (`DEC-ML-2.0-TARGET`):
   - `target_pf_lift = 0.10` accepted as the GO threshold;
   - `conditional_band_pf_lift_floor = 0.055` accepted (Option A: above MDE_upper of 0.0503);
   - `comparator = baseline_XGB_on_survivors_only_locked_hparams` accepted (harder than rule-baseline; documented mitigation);
   - Q1 thresholds `-1σ_cross / -2σ_cross + breadth ≥3/5` accepted on the secondary cohort only.
3. **Amendment A1** (`DEC-ML-1.6b-A1-AUTHORIZATION`): sequential 1D-CNN
   features explicitly excluded from the Phase 2 primary endpoint.
4. **Bias self-audit**: each entry has the full 8-field self-audit with
   non-empty `*_note` strings. (The `verify_decision_log_schema.py`
   validator will enforce this when entries are appended.)

## To Approve

When ready to lock these into the canonical decision log:

```powershell
# 1. Append each draft (one line at a time) to the live log:
Get-Content Goblin\decisions\drafts\DEC-ML-2.0-CANDIDATES.draft.jsonl    | Add-Content Goblin\decisions\ml_decisions.jsonl
Get-Content Goblin\decisions\drafts\DEC-ML-2.0-TARGET.draft.jsonl        | Add-Content Goblin\decisions\ml_decisions.jsonl
Get-Content Goblin\decisions\drafts\DEC-ML-1.6b-A1-AUTHORIZATION.draft.jsonl | Add-Content Goblin\decisions\ml_decisions.jsonl

# 2. Replace each "PENDING_OWNER_APPROVAL" timestamp in the appended lines
#    with the actual UTC approval timestamp before the validator runs:
#    (do this in your editor; keep one entry = one line)

# 3. Validate:
.\.venv\Scripts\python.exe -B tools/verify_decision_log_schema.py

# 4. Sign + commit:
git add Goblin/decisions/ml_decisions.jsonl
git commit -S -m "chore(ml-2.0): pre-register DEC-ML-2.0-CANDIDATES, -TARGET, -1.6b-A1"

# 5. Move drafts to an archive subfolder (do not delete; audit trail):
git mv Goblin/decisions/drafts Goblin/decisions/drafts.approved.20260421
git commit -m "chore(ml-2.0): archive approved drafts"
```

## To Reject / Revise

- Edit any draft file (still ends in `.draft.jsonl` to make schema check ignore it).
- Re-run the EX-2 sensitivity report if any threshold is changed
  (`python tools/gate_sensitivity.py --check-determinism`).
- Re-run this draft preparation step.

**No automatic appends. The kernel does not write these without owner action.**
