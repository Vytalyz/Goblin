# Goblin Evolution

This document records major program milestones and the intended evolution path from the current state to the future Goblin-controlled system.

## Current Milestones

### 2026-04-14: demo-account MT5 automation policy alignment completed

- top-level repo governance now explicitly allows governed MT5 demo-account EA automation under the Goblin live-demo contract
- real-money automated trading remains forbidden at the top-level policy layer
- repo-level instructions now match the completed live-demo observability and deployment-ladder phases instead of implying an unconditional MT5 automation ban

### 2026-04-13: operational readiness hardening completed (P13-P15)

- P13 inventory report published with subsystem coverage and explicit gap analysis
- P14 session-aware run logging implemented with `GoblinRunRecord`, deterministic `session_window` derivation, and campaign entrypoint integration
- P15 clean-room governance implemented with seven auditable rules, baseline scenarios, pattern-card template, and framework gap matrix

### 2026-04-13: namespace takeover completed (T1-T4)

- operator-facing identity moved to Goblin-first wording and CLI entrypoints
- compatibility bridge introduced via `src/goblin/` namespace wrappers
- project package identity switched to `goblin` with `agentic-forex` command retained as compatibility shim
- legacy `agentic_forex` namespace explicitly marked as compatibility-only with documented deprecation path

### 2026-04-12: Goblin foundation established

- Goblin created as the umbrella program under `/Goblin`
- program, roadmap, status, phase, contract, template, checkpoint, and runbook structure added
- Goblin state made machine-readable through `program_status.json` and per-phase state files

### 2026-04-12: four-channel truth stack established

- `research_backtest` defined as research truth
- `mt5_replay` defined as executable validation truth
- `live_demo` defined as operational truth
- `broker_account_history` defined as reconciliation truth

### 2026-04-12: provenance layer established

- explicit evidence-channel and artifact provenance structures added
- channel-owned artifact indexes introduced
- Goblin artifact registration and validation helpers added

### 2026-04-12: time/session normalization completed

- default research-data contract builder added
- default time/session contract builder added
- truth-alignment reports now declare a comparison time basis and surface mismatches
- OANDA ingest and backfill outputs now record the frozen acquisition contract in provenance

### 2026-04-12: MT5 certification gate completed

- Goblin MT5 certification artifacts are now written for official parity, diagnostic parity, and incident replay runs
- official MT5 parity authority now requires `deployment_grade` certification instead of inferring authority from tester mode alone
- incident replay trust now depends on a passed baseline known-good harness reproduction
- harness trust classification is separated from candidate alpha claims through `deployment_grade`, `research_only`, and `untrusted`

### 2026-04-12: live-demo observability and broker reconciliation completed

- live-demo attach manifests, runtime summaries, and heartbeat series now captured and persisted under the `live_demo` channel
- heartbeat anomaly detection surfaces chaos conditions: terminal close, sleep/wake, account change, algo-trading disabled, and stale audit
- broker reconciliation pipeline parses MT5 account history CSV and matches against EA audit by ticket
- `BrokerReconciliationReport` classifies matched, missing-broker, and extra-broker trades and computes cash PnL delta
- live-demo channel is no longer self-referential; `broker_account_history` now provides independent external verification
- full operational contracts written for both channels; 10 targeted tests pass

### 2026-04-12: incident severity and SLA governance completed (P06)

- `IncidentRecord` now carries `severity` (S1–S4), `sla_class`, `incident_type`, `ladder_state_at_incident`, and `deployed_bundle_id`
- `validate_incident_closure` enforces required closure evidence per severity before an incident can be closed
- `close_incident_record` raises `ValueError` if required fields are missing for the incident's severity class
- `list_open_blocking_incidents` returns open or monitoring S1/S2 incidents that block new live attaches and ladder advancement
- `INCIDENT_RESPONSE.md` runbook rewritten with severity-driven step-by-step procedures
- 17 targeted tests pass

### 2026-04-12: deployment ladder and release gating completed (P07)

- `LiveAttachManifest` now carries `ladder_state`, `broker_server`, and `bundle_id` — no attach can occur without a declared ladder state
- `IncidentClosurePacket` carries `deployed_bundle_id` and `ladder_state_at_incident` for full audit trail
- `validate_attach_against_bundle` checks `inputs_hash` between the approved bundle and the attach manifest; mismatch automatically opens a `release_integrity_failure` S1 incident
- `DeploymentLadderState` type defined with all five states: `shadow_only`, `limited_demo`, `observed_demo`, `challenger_demo`, `eligible_for_replacement`
- `RELEASE_AND_ROLLBACK.md` runbook rewritten with ladder advancement rules, hash-check procedures, and rollback steps
- 7 targeted tests pass

### 2026-04-12: investigation and evaluation framework completed (P08)

- `build_incident_investigation_pack` now writes reproducible investigation artifacts for frozen incidents
- each pack persists scenario JSONs, a trace JSON, an evaluation suite, and a frozen benchmark-history snapshot
- artifact filenames are compact and deterministic so the workflow remains usable under Windows path-length limits
- AF-CAND-0263 same-window postpatch incident now has a real investigation pack under `Goblin/reports/investigations/`
- 40 targeted Goblin tests pass across investigation, controls, incident, CLI, and program surfaces

### 2026-04-12: strategy governance implementation resumed (P09 in progress)

- `GOBLIN-P09` moved from ready to in-progress in phase state tracking
- family-level experiment accounting ledger model and writer were implemented with permissive budget caps
- governed operator actions now enforce strategy governance by requiring a family rationale card and blocking suspended families
- CLI gained `goblin-write-experiment-ledger` for deterministic artifact emission and operator inspection
- targeted tests cover ledger suspension behavior and governed-action gating prerequisites

### 2026-04-13: invalid-comparison enforcement wired into experiment comparison (P09 continuation)

- `compare_experiments` now validates comparison contract prerequisites before ranking candidates
- explicit candidate comparisons are hard-rejected when in-sample/out-of-sample splits, cross-window bounds, or regime accounting are missing
- broad family scans now exclude invalid artifacts and persist exclusion reasons in comparison reports for audit visibility
- targeted comparison/operator/Goblin tests pass after enforcement wiring

### 2026-04-13: methodology rubric audit workflow wired into strategy governance (P09 continuation)

- family-level strategy methodology audits are now written under `Goblin/reports/strategy_methodology_audits/`
- governed actions are blocked when methodology rubric score falls below the configured floor
- strategy-governance manifest summaries now include methodology audit evidence path and score/pass status
- a dedicated strategy-methodology rubric contract was added and included in Goblin contract initialization

### 2026-04-13: strategy governance phase completed (P09)

- direct legacy campaign entrypoints now enforce strategy-governance family gates, preventing suspension bypass outside the operator wrapper
- live/demo progression paths now enforce candidate-level governance and experiment-lineage checks before publish and MT5 packet generation
- promotion decision packets now include experiment-accounting and methodology-audit references with search-bias narrative summaries
- focused governance/campaign/live-demo regression suite passed (`153` tests)

### 2026-04-12: portfolio governance and promotion policy enforcement completed (P10)

- Promotion packets now require explicit statistical policy key citations from `config/eval_gates.toml`; free-text judgment is rejected at write time.
- Promotion decisions are blocked below `observed_demo` ladder state; missing ladder state is a hard error.
- Material deployment-fit deltas (`≥ 0.05`) require a new deployment bundle reference in the promotion packet.
- Portfolio cycle now gates challenger lane progression on an existing promotion packet for the handoff candidate.
- Challenger-vs-benchmark identity conflict is detected and surfaced as a blocked slot report.
- Locked benchmark candidate reference auto-surfaced in every gap slot cycle note.
- Candidate scorecard and promotion packet contracts updated with enforcement rules.
- 24 targeted tests pass across Goblin controls and portfolio layer.

### 2026-04-13: governed ML controls completed (P11)

- Trusted label policy artifacts now require ambiguity rejection criteria and explicit truth-channel constraints.
- Offline training cycle artifacts now require holdout windows and MT5 certification evidence when a model touches live execution.
- Model registry entries now link label-policy and training-cycle artifact paths under Goblin report surfaces.
- Runtime governance now blocks online self-tuning and blocks unapproved models for live-touching use.
- Focused P11 regression suite added in `tests/test_goblin_ml.py`.

### 2026-04-13: knowledge store, vector memory, and bounded agent layer completed (P12)

- Structured knowledge events are now persisted as append-only JSONL under Goblin knowledge reports.
- Retrieval documents can now be persisted and indexed into deterministic vector memory.
- Retrieval queries now produce provenance-cited advisory responses (document id + source hash citations).
- Bounded Goblin agent roles now enforce governance boundaries, blocking approval/promotion/deployment/bypass actions.
- Focused P12 regression suite added in `tests/test_goblin_p12.py`.

### 2026-06-14: full phase validation audit completed

- Comprehensive diagnostic review of all 13 phases (P00–P12) executed before migration/takeover plan review.
- 183/183 tests green (133 core + 50 day-trading).
- 10 issues discovered across 7 files and resolved: P07 state file tracking discrepancy, P05/P09 test governance bootstrap gap, stale day-trading variant assertion, 5 program loop rationale card bootstraps, test-infrastructure PDF path leak, and one production-code bug (comparison validator `in_sample` vs `train` label mismatch in `service.py`).
- Audit report written to `Goblin/reports/phase_validation_audit_20260614.md`.

### 2026-04-14: S1+ remaining-plan roadmap captured

- the remaining post-takeover Goblin work is now formalized in `Goblin/S1_PLUS_PLAN.md`
- the plan is organized into nine operational phases and four bundled checkpoints
- Goblin now distinguishes clearly between completed platform phases and the still-unstarted sequential strategy program

## Near-Term Evolution Order

1. All current roadmap phases (`GOBLIN-P00` to `GOBLIN-P12`) are complete under tracked scope.
2. Full phase validation audit completed.
3. Operational readiness phases P13–P15 harden Goblin for production use.
4. T1–T4 namespace takeover migrates identity from `agentic_forex` to `Goblin`.
5. Multi-timezone/archetype strategy program (S1+) begins after full Goblin operational status.

## Evolution Rule

Goblin evolves in layers:

- first: truth, provenance, replay, and reconciliation
- second: incident, release, and approval control
- third: strategy search and evaluation quality
- fourth: governed intelligence, retrieval, and future namespace takeover
- fifth: sequential multi-timezone strategy development using the completed Goblin system

Anything that skips those layers risks repeating the same control-plane failure Goblin was created to solve.
