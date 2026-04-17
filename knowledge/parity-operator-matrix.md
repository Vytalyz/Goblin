# Parity Operator Matrix

This file is the operator-facing control surface for current parity scope. It is intentionally shorter than the raw policy file and should be read alongside `knowledge/parity-lineage-audit.md`.

## Frozen Reference Candidates

| Candidate | Family | Official Parity Class | Official Parity Allowed | Diagnostic Allowed | Current Status |
| --- | --- | --- | --- | --- | --- |
| `AF-CAND-0239` | `session_momentum_band_research` | `m1_official` | yes | yes | `research-valid, parity-blocked, operationally unproven under current official M1 parity standard` |

## Current In-Scope Lineages

| Family | Hypothesis Class | Seed Roots | Official Parity Class | Official Parity Allowed | Diagnostic Allowed | Current Scope Status |
| --- | --- | --- | --- | --- | --- | --- |
| `asia_range_bridge_research` | `compression_reversion` | `AF-CAND-0265` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `asia_range_bridge_research` | `drift_reclaim` | `AF-CAND-0267` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `asia_range_bridge_research` | `range_reclaim` | `AF-CAND-0266` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `europe_open_continuation_research` | `session_momentum_band` | `AF-CAND-0271` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `europe_open_continuation_research` | `volatility_expansion` | `AF-CAND-0269` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `europe_open_continuation_research` | `volatility_retest_breakout` | `AF-CAND-0270` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `high_vol_overlap_persistence_bridge_research` | `high_vol_overlap_persistence_retest` | `AF-CAND-0253, AF-CAND-0254, AF-CAND-0255` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `new_york_event_retest_research` | `volatility_expansion` | `AF-CAND-0273` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `new_york_event_retest_research` | `volatility_retest_breakout` | `AF-CAND-0272, AF-CAND-0274` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `overlap_persistence_bridge_research` | `overlap_persistence_retest` | `AF-CAND-0259, AF-CAND-0260, AF-CAND-0261` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `overlap_resolution_bridge_research` | `overlap_persistence_retest` | `AF-CAND-0262, AF-CAND-0263, AF-CAND-0264` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `session_momentum_band_research` | `session_momentum_band` | `AF-CAND-0238, AF-CAND-0239, AF-CAND-0240` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `session_momentum_bridge_research` | `session_momentum_band` | `AF-CAND-0250, AF-CAND-0251, AF-CAND-0252` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `session_momentum_cushion_research` | `session_momentum_band` | `AF-CAND-0245, AF-CAND-0246, AF-CAND-0247` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `session_momentum_hold_research` | `session_momentum_band` | `AF-CAND-0241, AF-CAND-0242, AF-CAND-0243` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `us_late_unwind_research` | `compression_reversion` | `AF-CAND-0277` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `us_late_unwind_research` | `range_reclaim` | `AF-CAND-0276` | `m1_official` | yes | yes | `in_scope_under_current_m1` |
| `us_late_unwind_research` | `session_extreme_reversion` | `AF-CAND-0275` | `m1_official` | yes | yes | `in_scope_under_current_m1` |

## Explicit Tick-Required Lineages

- None.

## Current Review-Needed Lineages

| Family | Hypothesis Class | Seed Roots | Official Parity Class | Official Parity Allowed | Diagnostic Allowed | Current Scope Status |
| --- | --- | --- | --- | --- | --- | --- |
| `resilience_bridge_research` | `failed_break_fade` | `AF-CAND-0183` | `<unset>` | no | yes | `review_needed_before_official_parity` |
| `resilience_bridge_research` | `session_breakout` | `AF-CAND-0181` | `<unset>` | no | yes | `review_needed_before_official_parity` |
| `resilience_bridge_research` | `trend_retest` | `AF-CAND-0182` | `<unset>` | no | yes | `review_needed_before_official_parity` |

## Conflicting Parity Assignments

- None.

## Archival Or Reference-Only Families

These families remain in the repo for evidence lineage, but their latest governed outcomes already closed them materially. Treat them as archival unless explicitly reopened through policy.

- `compression_resilience_research`
- `context_selective_research`
- `directional_edge_research`
- `high_vol_overlap_persistence_research`
- `horizon_momentum_research`
- `impulse_transition_research`
- `intraday_regime_research`
- `market_structure_research`
- `overlap_balance_research`
- `overlap_event_retest_research`
- `overlap_persistence_band_research`
- `overlap_persistence_research`
- `quality_gate_research`
- `release_retest_research`
- `session_alignment_research`
- `stationary_reclaim_research`
- `structure_transition_research`
- `throughput_research`
- `volatility_retest_research`

## Working Rule

- Only explicit `m1_official` lineages are currently eligible for official parity.
- `<unset>` never means implicit `m1_official`.
- Diagnostic parity may be used to explain failures, but it cannot establish promotion truth.
- If a review-needed lineage is reopened, classify it prospectively before any official parity run.
