# Goblin Phase Brief

This file summarizes what each Goblin phase is for and what work happens when that phase becomes active. Use `Goblin/STATUS.md` for live state.

## Phase Transition Rule

1. Finish the current phase and verify its exit criteria in code, artifacts, and tests.
2. Update the Goblin tracking surfaces for the active phase.
3. Record acceptance evidence and write a phase checkpoint.
4. Stop at the phase boundary and wait for explicit approval before starting the next phase.

## Phase Summary

| Phase | Purpose | What We Do When It Starts | Done When |
| --- | --- | --- | --- |
| `GOBLIN-P00` | Foundation | establish `/Goblin`, state/checkpoint plumbing, CLI surfaces, and the umbrella-program docs without renaming `src/agentic_forex` | Goblin is the tracked program layer for all later phases |
| `GOBLIN-P01` | Truth stack | define `research_backtest`, `mt5_replay`, `live_demo`, and `broker_account_history` as separate truth channels and wire their comparison contracts | promotion and validation logic stop treating truth channels as interchangeable |
| `GOBLIN-P02` | Provenance | require explicit provenance, evidence-channel tagging, immutable run identity, and channel-owned indexes | governed workflows stop accepting ambiguous artifacts |
| `GOBLIN-P03` | Time/data normalization | freeze the OANDA acquisition contract, declare the canonical time/session basis, and add research data-quality gates | comparisons share the same declared time basis and OANDA research ingest is reproducible |
| `GOBLIN-P04` | MT5 certification | define the MT5 certification envelope, write certification artifacts, require baseline harness trust for incident replay, and gate MT5 authority on certification status | no MT5 replay is treated as authoritative without Goblin harness certification |
| `GOBLIN-P05` | Live/broker observability | add live attach manifests, runtime summaries, heartbeats, broker reconciliation with MT5 primitives, execution cost contract, and statistical decision policy | live-demo truth no longer depends only on EA self-logs; all cross-channel execution assumptions are declared |
| `GOBLIN-P06` | Incident system | define incident severity matrix (S1-S4), SLA as operational-event-relative deadlines, and update runbook with severity-driven closure requirements | unexplained material deltas open an incident with a severity that drives suspension and required evidence |
| `GOBLIN-P07` | Release/approval control | define deployment ladder (5 states), environment reproducibility (terminal pinning, config drift, secrets policy), and bundle-ladder separation | no live/demo attachment can happen without a governed bundle and a declared ladder state |
| `GOBLIN-P08` | Investigation/evals | add reproducible investigation traces, scenarios, and benchmarked evaluation suites | serious incidents produce repeatable investigation packs |
| `GOBLIN-P09` | Strategy governance | add rationale cards, experiment accounting with per-family budget caps and suspension thresholds, and invalid comparison rules | no live/demo candidate exists without rationale and experiment lineage; experiment budgets enforced |
| `GOBLIN-P10` | Portfolio program | resume governed strategy search with candidate scorecards, deployment profiles, and promotion packets anchored to statistical policy and deployment ladder | alpha claims cannot hide deployment-fit changes; promotion requires policy-key citations and ladder state |
| `GOBLIN-P11` | Governed ML | add the model registry, trusted label policy, and offline training/validation controls | no online self-tuning reaches live or demo execution |
| `GOBLIN-P12` | Knowledge/agents | add knowledge lineage, retrieval policy, and bounded Goblin agent roles | agentic features cannot weaken governance or runtime truth |
