# Codex Goblin Instructions

This file is the human-facing Codex playbook for Goblin work in this repo. `AGENTS.md` remains the authoritative auto-read rule file, but this document defines the operating discipline that must be kept current for Goblin execution.

## Primary References

Read these before doing Goblin work:

- `Goblin/PROGRAM.md`
- `Goblin/ROADMAP.md`
- `Goblin/ML_EVOLUTION_PLAN.md`
- `Goblin/S1_PLUS_PLAN.md`
- `Goblin/STATUS.md`
- `Goblin/IMPLEMENTATION_TRACKER.md`
- `Goblin/MATURITY.md`
- `Goblin/EVOLUTION.md`
- `Goblin/PHASE_BRIEF.md`
- `Goblin/TAKEOVER_PLAN.md`
- `Goblin/decisions/ml_decisions.jsonl` (append-only ML decision log; 9 entries; validated by `tools/verify_decision_log_schema.py`)
- `Goblin/decisions/predictions.jsonl` (R4-11 mid-process predictions log; currently empty; schema at `Goblin/decisions/PREDICTIONS_SCHEMA.md`)
- `Goblin/reports/ml/p2_0_rehearsal_report.json` (EX-10 E2E rehearsal report; overall=PASS 6/6)

## Required Goblin Tracking Discipline

When a change affects Goblin planning, implementation, governance, validation, or migration:

1. Update the code and artifacts for the active phase only.
2. Update the phase state and current progress record.
3. Update `Goblin/IMPLEMENTATION_TRACKER.md` to distinguish:
   - fully implemented
   - partially implemented
   - scaffold only
   - not started
4. Update `Goblin/MATURITY.md` if the maturity of any subsystem changes.
5. Update `Goblin/EVOLUTION.md` if the program milestone or migration posture changes.
6. Update `Goblin/TAKEOVER_PLAN.md` if the path from `agentic_forex` to `Goblin` changes.
7. Stop at the end of the current phase and ask the user to continue. Do not silently roll into the next phase.

## Phase Sequencing Rule

- Execute Goblin phases strictly in dependency order.
- One active implementation phase at a time.
- Do not mark a phase complete just because documents or models exist. Completion requires implementation evidence and verification against the phase exit criteria.
- Do not treat green diagnostics by themselves as phase completion if the phase exit criteria are still unmet.
- If only scaffolding exists, record it as scaffolding. Do not label it complete.
- For MT5-targeted deployment, do not treat an `MT5ParityReport` as authoritative unless it carries `certification_status == deployment_grade` and points to the Goblin certification artifact.
- Governed MT5 demo-account EA attaches are allowed only when they satisfy the live-demo contract, deployment bundle checks, and ladder-state requirements.
- Do not treat demo-account automation evidence as permission for real-money automation.

## Completion Standard

A Goblin phase is only complete when:

- its planned artifacts exist
- the implementation scope for that phase is actually delivered
- verification evidence exists
- the status docs and tracker docs are updated
- serious-incident phases record a reproducible investigation artifact when the exit criteria require it
- the next step is explicit

## Clean Takeover Rule

The repo identity is `Goblin`. The `agentic_forex` kernel namespace is preserved for compatibility:

- `src/agentic_forex` remains the runtime kernel (until explicit migration)
- Goblin is the umbrella control plane and primary identity
- migration is tracked in `Goblin/TAKEOVER_PLAN.md`

Current takeover posture:

- T1-T4 are completed and recorded in Goblin phase state/checkpoint surfaces
- `src/goblin` is the primary operator-facing namespace bridge
- `agentic_forex` remains compatibility-only until downstream callers fully migrate
- compatibility must be preserved until the takeover criteria are satisfied

## Reporting Standard

Any Goblin progress summary should state:

- active phase
- whether a phase gate found real completion or only partial implementation
- what was implemented
- what remains missing
- what is only scaffolded
- tests or verification run
- artifacts written
- whether the phase is complete or still in progress

## P12 Completion Boundary

`GOBLIN-P12` is complete. Current control expectations:

- structured knowledge events are append-only and persisted under Goblin knowledge reports
- retrieval documents/index/queries are advisory-only and must include provenance-cited sources
- bounded agent roles cannot execute approval, promotion, deployment, or governance-bypass actions
- retrieval remains subordinate to governance and validation records
- targeted P12 suite exists in `tests/test_goblin_p12.py`
- no further phase start is required under the current Goblin roadmap scope

## Live-Demo Operator Commands

Shadow-only and live-demo attaches use the following CLI workflow:

```sh
# 1. Record the governed attach (validates bundle hash, writes manifest)
goblin goblin-live-attach --candidate-id AF-CAND-0733 --run-id live-demo-<UTC> --terminal-build <BUILD> --bundle-id <BUNDLE_ID>

# 2. During session: periodic heartbeats
goblin goblin-live-heartbeat --candidate-id AF-CAND-0733 --run-id <RUN_ID> --status healthy --terminal-active true --algo-trading-enabled true

# 3. After session: collect EA outputs into governed artifacts
goblin goblin-live-session-end --candidate-id AF-CAND-0733 --run-id <RUN_ID> --mt5-common-path "C:\...\Terminal\Common\Files"
```

Artifacts land in `Goblin/reports/live_demo/<candidate_id>/<run_id>/`.
