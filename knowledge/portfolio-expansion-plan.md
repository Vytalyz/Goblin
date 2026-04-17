# Portfolio Expansion Plan

## Current Lock

- `AF-CAND-0263` is the active overlap-session demo candidate.
- Keep it unchanged while operator-side MT5 evidence is collected.
- Treat the current demo window as evidence gathering, not a mutation window.
- The overlap slot is now represented as a locked benchmark portfolio slot, not just an informal roadmap note.
- The next non-overlap strategy search is represented as a separate blank-slate portfolio slot with independent mutation rights.

## Revisit Triggers

- `3-5` trading days: confirm the EA stays attached correctly and starts trading inside the intended overlap hours.
- `10` demo trades or roughly `1-2` weeks: first meaningful operator review checkpoint.
- `20-30` demo trades: stronger demo-readiness checkpoint before any broader deployment discussion.

## Working Rule

- Do not stretch `AF-CAND-0263` across the full day to force more trades.
- Build additional time-window coverage by adding orthogonal families.
- Every new family must be assigned an explicit parity class prospectively before official parity.
- Treat the portfolio as one repo-native coordinator over multiple slots, not as separate uncontrolled autonomous systems.
- Keep Codex as the outer orchestration layer; the Python/TOML control plane remains authoritative.

## Monitoring Backlog

- Capture a later-stage `true agentic monitoring` milestone for MT5 operator-side runs.
- Scope for that milestone:
  - ingest MT5 `Experts` and terminal `Journal` logs from the active terminal data folder
  - map log events back to `candidate_id`, `magic_number`, and active run lineage
  - tail new log lines during live-demo operation instead of relying only on post-run archives
  - preserve the EA audit CSV as the primary structured runtime ledger and use GUI-log ingestion as supplemental observability
- Reason for deferral:
  - the current demo checkpoint for `AF-CAND-0263` can be monitored reliably enough from the audit CSV
  - the next strategic bottleneck is still strategy-library expansion, not MT5 log transport

## Codex Automation State

- Repo-local Codex slot metadata, custom agents, and paused automation definitions now exist.
- The intended gap-lane execution mode is `app_automation_worktree`.
- Actual worktree activation is deferred until this project is moved onto its own Git root or otherwise given a safe worktree-capable repository boundary.
- Until then:
  - the automations stay paused
  - the portfolio coordinator and slot policy remain the authoritative implementation
  - no background mutation should be scheduled against the current broad parent Git checkout

## Next Family Order

1. `asia_range_bridge_research`
   - status: completed and retired under governed data/label audit
   - outcome: `AF-CAND-0268` became the family reference, but the whole family failed under a shared label contract and did not justify reopening
2. `europe_open_continuation_research`
   - status: completed and retired under governed data/feature audit
   - objective: test whether pre-overlap directional handoff after Europe open could be added without stretching `AF-CAND-0263` across the full day
   - seed roots: `AF-CAND-0269`, `AF-CAND-0270`, `AF-CAND-0271`
   - class rule: assign `m1_official` prospectively and keep the family inside bar-based continuation / retest behavior
3. `new_york_event_retest_research`
   - status: blocked by governed novelty and archetype-retirement controls before a clean family run could complete
   - seed roots: `AF-CAND-0272`, `AF-CAND-0273`, `AF-CAND-0274`
   - outcome: the family did not justify reopening the older event / retest archive under a new name, which is the intended behavior of the current policy layer
4. `us_late_unwind_research`
   - status: completed without a viable candidate
   - objective: test whether the late-U.S. unwind after the overlap impulse could become an orthogonal mean-reversion slot
   - seed roots: `AF-CAND-0275`, `AF-CAND-0276`, `AF-CAND-0277`
   - outcome: `AF-CAND-0276` became the family reference branch, but it still failed walk-forward and stress with no justified bounded mutation
5. next recommended direction
   - completed interim overlap mean-reversion scan:
     - artifact: `reports/policy/overlap_mean_reversion_gap_scan_20260328.json`
     - outcome: no full-sample-positive overlap mean-reversion variant survived the rough scan, even though several high-volatility `failed_break_fade` slices looked better in the latest out-of-sample window
   - completed contract-alignment check against the active overlap winner:
     - artifact: `reports/policy/overlap_contract_alignment_audit_20260328.json`
     - outcome: backtest-versus-label exit mismatch is material on both `AF-CAND-0263` and the best overlap mean-reversion slice, so it is not enough to justify reopening the gap family by itself
   - next strategy move:
     - do not add another approved overlap mean-reversion lane under the current contract
     - first make a contract-level decision on whether mean-reversion families should keep the current bar-based exit semantics or move to a revised research contract
     - only after that decision should another overlap mean-reversion family be seeded

## Intended Portfolio Shape

- `AF-CAND-0263`: overlap-session persistence retest
- retired experiment: Asia/range family did not hold up under governed evaluation
- retired experiment: Europe-open continuation family did not hold up under governed evaluation
- blocked experiment: New York / overlap event-retest reopening did not clear novelty / retirement controls
- failed experiment: late-U.S. unwind family did not produce a stable reference branch
- scan result: rough overlap mean-reversion variants did not justify immediate promotion into a new governed family
- contract result: exit-semantics mismatch exists, but it is not uniquely worse on the gap family than on `AF-CAND-0263`
- next target: contract decision first, then only seed a new overlap mean-reversion family if that family class is reapproved under a clearer research contract
- later target: only revisit broader time-window coverage if a future family survives governed evaluation outside overlap

## Rationale

- The current candidate already shows a context-specific edge in overlap.
- Forcing it to trade all sessions is more likely to dilute that edge than improve it.
- A portfolio of orthogonal, session-specific strategies is the cleaner path toward broader time coverage.
- The first four gap-finding attempts now tell a clearer story:
  - quiet-session balance does not hold up
  - broad Europe-open continuation does not hold up
  - the old event / retest archive is correctly blocked from being quietly reopened
  - late-U.S. unwind does not currently survive robustness
- The rough overlap mean-reversion scan adds one more constraint:
  - there may be a later-segment failed-break fade niche, but the current label contract does not make it robust enough to justify a governed family seed yet
- The contract-alignment check adds one more boundary:
  - current backtest-versus-label exit mismatch is a broader contract issue, not a special excuse for the gap family
  - so the honest next step is a class-level contract decision, not another weak overlap mean-reversion seed
