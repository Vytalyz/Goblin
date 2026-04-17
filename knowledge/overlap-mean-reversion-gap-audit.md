# Overlap Mean-Reversion Gap Audit

## Context

- `AF-CAND-0263` remains the active overlap-session demo candidate.
- The first gap search across Asia, Europe-open continuation, New York event-retest reopening, and late-U.S. unwind did not produce a second governed slot.
- The next plausible portfolio expansion path is regime-orthogonal overlap, not another weak non-overlap family guess.

## Scan Artifact

- Scan report: `reports\policy\overlap_mean_reversion_gap_scan_20260328.json`
- Scan focus: overlap-session mean-reversion archetypes that intentionally exclude `trend_context` and therefore complement `AF-CAND-0263`
- Base template: `AF-CAND-0275` research contract, retargeted to overlap-session mean-reversion variants without writing new governed trial artifacts

## Variants Scanned

- `failed_break_fade`
- `session_extreme_reversion`
- `range_reclaim`
- `compression_reversion`
- refined hour / threshold / hold variants for high-volatility `failed_break_fade`

## Findings

- No scanned overlap mean-reversion variant produced a positive full-sample profile.
- `positive_full_sample_count = 0`
- Several refined `failed_break_fade` variants produced superficially positive out-of-sample profit factors, but all retained negative full-sample expectancy and sub-1.0 full-sample profit factor.
- Best rough niche:
  - `entry_style = failed_break_fade`
  - `hours = [14, 15, 16]`
  - `required_volatility_bucket = high`
  - `exclude_context_bucket = trend_context`
  - `out_of_sample_profit_factor = 1.4799`
  - `profit_factor = 0.5865`
  - `expectancy_pips = -1.1466`

## Contract Alignment Check

- Contract-alignment artifact: `reports\policy\overlap_contract_alignment_audit_20260328.json`
- Control reference: `AF-CAND-0263`
- Control exit-reason mismatch rate between current deterministic backtest exits and path-aware label exits: `0.3111`
- Best overlap mean-reversion audit variant (`failed_break_fade`, hours `14,15,16`) mismatch rate: `0.2797`
- Interpretation:
  - the backtest-versus-label exit semantic mismatch is real
  - it is not uniquely worse on the overlap mean-reversion slice than on the active overlap winner
  - so that mismatch does not rescue the gap family by itself

## Interpretation

- The current feature / label contract can isolate overlap mean-reversion slices that look better in the latest out-of-sample segment than they do in the full search window.
- That is not enough to justify a new governed family seed yet.
- The pattern is more consistent with label drift or regime instability than with a robust second edge.
- The additional contract-alignment check narrows this further:
  - the current exit-semantics mismatch is a broader contract issue, not a gap-specific explanation
  - the overlap mean-reversion slice still fails the full-sample bar even before any contract redesign is approved
- The next bottleneck is therefore not missing entry-style variety alone; it is whether a deliberate research-contract change for mean-reversion families is worth doing before more governed seeding.

## Next Strategy Step

- Do not seed a new overlap mean-reversion family under the current governed contract.
- Before any future mean-reversion family seed, make a contract-level decision:
  - either accept the current bar-based backtest exit model as the official research truth
  - or approve a bounded redesign of mean-reversion contract semantics and re-evaluate the family class under that new contract
- Only reopen overlap mean-reversion after that decision, not through another local family mutation.
