# Overlap Contract Alignment Audit

## Scope

- Compare the current deterministic backtest exit contract against the path-aware label contract.
- Use `AF-CAND-0263` as the control winner.
- Use the best rough overlap mean-reversion slice from the gap scan as the audit variant.

## Artifact

- `reports\policy\overlap_contract_alignment_audit_20260328.json`

## Key Result

- `AF-CAND-0263` exit-reason mismatch rate: `0.3111`
- overlap failed-break audit variant mismatch rate: `0.2797`

## Interpretation

- The current research contract has a real exit-semantics mismatch between:
  - the bar-based deterministic backtest engine
  - the path-aware label builder
- That mismatch is not uniquely worse on the overlap mean-reversion slice than on the active overlap winner.
- So the missing portfolio slot cannot be explained away as “the fade family only loses because the exit contract is harsher there.”

## Strategy Consequence

- Do not reopen overlap mean-reversion under the current contract just because the gap scan found a few positive out-of-sample slices.
- The next move, if mean-reversion remains strategically important, is a class-level contract decision:
  - keep the current bar-based research truth
  - or explicitly redesign the mean-reversion research contract and reassess the family class under that revised contract

## Operational Recommendation

- Keep `AF-CAND-0263` unchanged while demo evidence accumulates.
- Do not seed another overlap mean-reversion family until the contract decision is made.
- Use the waiting period to decide whether mean-reversion is important enough to justify a deliberate research-contract redesign.
