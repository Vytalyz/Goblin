# Parity Lineage Audit

- Audit date: `2026-03-26`
- Scope: active throughput and promotion lanes in `config/program_policy.toml`
- Goal: confirm explicit parity-class coverage after parity-class enforcement was added

## Summary

- Total active family or hypothesis-class lineages: `64`
- Explicit parity-class lineages: `18`
- Current unresolved review-needed lineages: `3`
- Archival or reference-only unresolved lineages: `43`
- Unset parity-class lineages: `46`
- Conflicting parity-class lineages: `0`

## Conservative Scope Decision

- Current official scope remains conservative.
- Only lineages with an explicit `parity_class = "m1_official"` are currently in scope for official parity.
- Lineages with `parity_class = <unset>` are blocked for official parity until they are classified prospectively in policy.
- Diagnostic parity remains allowed as a non-authoritative investigation tool.

## Current Live Scope

### In Scope Now

- `asia_range_bridge_research / compression_reversion`
  - roots: `AF-CAND-0265`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `asia_range_bridge_research / drift_reclaim`
  - roots: `AF-CAND-0267`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `asia_range_bridge_research / range_reclaim`
  - roots: `AF-CAND-0266`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `europe_open_continuation_research / session_momentum_band`
  - roots: `AF-CAND-0271`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `europe_open_continuation_research / volatility_expansion`
  - roots: `AF-CAND-0269`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `europe_open_continuation_research / volatility_retest_breakout`
  - roots: `AF-CAND-0270`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `high_vol_overlap_persistence_bridge_research / high_vol_overlap_persistence_retest`
  - roots: `AF-CAND-0253, AF-CAND-0254, AF-CAND-0255`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `new_york_event_retest_research / volatility_expansion`
  - roots: `AF-CAND-0273`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `new_york_event_retest_research / volatility_retest_breakout`
  - roots: `AF-CAND-0272, AF-CAND-0274`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `overlap_persistence_bridge_research / overlap_persistence_retest`
  - roots: `AF-CAND-0259, AF-CAND-0260, AF-CAND-0261`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `overlap_resolution_bridge_research / overlap_persistence_retest`
  - roots: `AF-CAND-0262, AF-CAND-0263, AF-CAND-0264`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `session_momentum_band_research / session_momentum_band`
  - roots: `AF-CAND-0238, AF-CAND-0239, AF-CAND-0240`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
    - `AF-CAND-0239` remains frozen as `research-valid, parity-blocked, operationally unproven under current official M1 parity standard`
- `session_momentum_bridge_research / session_momentum_band`
  - roots: `AF-CAND-0250, AF-CAND-0251, AF-CAND-0252`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `session_momentum_cushion_research / session_momentum_band`
  - roots: `AF-CAND-0245, AF-CAND-0246, AF-CAND-0247`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `session_momentum_hold_research / session_momentum_band`
  - roots: `AF-CAND-0241, AF-CAND-0242, AF-CAND-0243`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `us_late_unwind_research / compression_reversion`
  - roots: `AF-CAND-0277`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `us_late_unwind_research / range_reclaim`
  - roots: `AF-CAND-0276`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard
- `us_late_unwind_research / session_extreme_reversion`
  - roots: `AF-CAND-0275`
  - parity class: `m1_official`
  - current status:
    - live under the current official standard

### Explicit Tick-Required Lineages

- None.

### Review Needed Before Any Future Official Parity


These lineages are not retired cleanly enough to be treated as archival only, but they are still unresolved and must not enter official parity until they are classified prospectively:

- `resilience_bridge_research / failed_break_fade`
  - roots: `AF-CAND-0183`
  - latest manager outcome: `watchdog_repeated_stop_reason:program_loop_max_cycles_reached`
- `resilience_bridge_research / session_breakout`
  - roots: `AF-CAND-0181`
  - latest manager outcome: `watchdog_repeated_stop_reason:program_loop_max_cycles_reached`
- `resilience_bridge_research / trend_retest`
  - roots: `AF-CAND-0182`
  - latest manager outcome: `watchdog_repeated_stop_reason:program_loop_max_cycles_reached`

Conservative interpretation:

- these remain `parity_class = <unset>`
- they are blocked for official parity
- they are the first unresolved lineages to classify if this family is reopened

## Archival Or Reference-Only Unresolved Scope

All other unresolved lineages are currently treated as archival or reference-only because their latest governed outcomes already closed them materially, for example:

- family retirement confirmed
- retire-family or retire-lane audit
- no pending approved lanes
- archetype retired
- low-novelty seed block

## Explicitly Classified Lineages

- `asia_range_bridge_research / compression_reversion`
  - roots: `AF-CAND-0265`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `asia_range_bridge_research / drift_reclaim`
  - roots: `AF-CAND-0267`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `asia_range_bridge_research / range_reclaim`
  - roots: `AF-CAND-0266`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `europe_open_continuation_research / session_momentum_band`
  - roots: `AF-CAND-0271`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `europe_open_continuation_research / volatility_expansion`
  - roots: `AF-CAND-0269`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `europe_open_continuation_research / volatility_retest_breakout`
  - roots: `AF-CAND-0270`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `high_vol_overlap_persistence_bridge_research / high_vol_overlap_persistence_retest`
  - roots: `AF-CAND-0253, AF-CAND-0254, AF-CAND-0255`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `new_york_event_retest_research / volatility_expansion`
  - roots: `AF-CAND-0273`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `new_york_event_retest_research / volatility_retest_breakout`
  - roots: `AF-CAND-0272, AF-CAND-0274`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `overlap_persistence_bridge_research / overlap_persistence_retest`
  - roots: `AF-CAND-0259, AF-CAND-0260, AF-CAND-0261`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `overlap_resolution_bridge_research / overlap_persistence_retest`
  - roots: `AF-CAND-0262, AF-CAND-0263, AF-CAND-0264`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `session_momentum_band_research / session_momentum_band`
  - roots: `AF-CAND-0238, AF-CAND-0239, AF-CAND-0240`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `session_momentum_bridge_research / session_momentum_band`
  - roots: `AF-CAND-0250, AF-CAND-0251, AF-CAND-0252`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `session_momentum_cushion_research / session_momentum_band`
  - roots: `AF-CAND-0245, AF-CAND-0246, AF-CAND-0247`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `session_momentum_hold_research / session_momentum_band`
  - roots: `AF-CAND-0241, AF-CAND-0242, AF-CAND-0243`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `us_late_unwind_research / compression_reversion`
  - roots: `AF-CAND-0277`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `us_late_unwind_research / range_reclaim`
  - roots: `AF-CAND-0276`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`
- `us_late_unwind_research / session_extreme_reversion`
  - roots: `AF-CAND-0275`
  - queue kinds: `promotion, throughput`
  - parity class: `m1_official`

## Main Audit Finding

- The repo now enforces parity class correctly, but the policy file is still mostly legacy-shaped.
- Only explicitly classified lineages are eligible for official parity.
- Review-needed unresolved lineages should be classified prospectively if their families are reopened.
- All other unresolved lineages are better treated as archival or reference-only until explicitly reopened.
- This is not an integrity bug anymore, because official parity will now block if unresolved lineages try to advance.

## Operational Rule After This Audit

- Do not treat `<unset>` as implicitly `m1_official`.
- Do not backfill parity class from candidate outcomes.
- Do not use diagnostic parity as promotion truth.
- If a lineage needs official parity, classify it first in `program_policy.toml`.

## Reference Candidates

- `AF-CAND-0239`
  - status: `research-valid, parity-blocked, operationally unproven under current official M1 parity standard`
  - source: `reports\AF-CAND-0239\operational_status.md`
