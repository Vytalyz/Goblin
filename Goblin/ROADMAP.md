# Goblin Roadmap

This roadmap is the tracked execution order for the Goblin V3 program.

## Execution Policy

- Implement one phase at a time in dependency order.
- Do not silently roll into the next phase.
- After each phase, update `STATUS.md`, `IMPLEMENTATION_TRACKER.md`, `MATURITY.md`, and `EVOLUTION.md`, then stop and ask the user whether to continue.

| Phase | Title | Depends On | Primary Deliverable |
| --- | --- | --- | --- |
| `GOBLIN-P00` | Program Foundation And Naming | `none` | `Goblin/PROGRAM.md` |
| `GOBLIN-P01` | Four-Channel Truth Stack | `GOBLIN-P00` | `Goblin/contracts/truth-stack.md` |
| `GOBLIN-P02` | Provenance And Artifact Contracts | `GOBLIN-P01` | `Goblin/contracts/artifact-provenance.md` |
| `GOBLIN-P03` | Time, Session, And Data Normalization | `GOBLIN-P02` | `Goblin/contracts/time-session-contract.md` |
| `GOBLIN-P04` | MT5 Harness And Executable Certification | `GOBLIN-P03` | `Goblin/contracts/mt5-certification.md` |
| `GOBLIN-P05` | Live Demo Observability And Broker Reconciliation | `GOBLIN-P04` | `Goblin/contracts/live-demo-contract.md` + `execution-cost-contract.md` + `statistical-decision-policy.md` |
| `GOBLIN-P06` | Incident And Safety Envelope System | `GOBLIN-P05` | `Goblin/contracts/incident-severity-matrix.md` + `incident-sla.md` |
| `GOBLIN-P07` | Release, Approval, And Change Management | `GOBLIN-P05` | `Goblin/contracts/deployment-ladder.md` + `environment-reproducibility.md` |
| `GOBLIN-P08` | Investigation And Evaluation Framework | `GOBLIN-P06` | `Goblin/contracts/investigation-trace.md` |
| `GOBLIN-P09` | Strategy Methodology, Search-Bias, And Experiment Governance | `GOBLIN-P08` | `Goblin/contracts/strategy-rationale-card.md` + `experiment-accounting.md` (with budget enforcement) |
| `GOBLIN-P10` | Portfolio And Candidate Strategy Program | `GOBLIN-P09` | `Goblin/contracts/candidate-scorecard.md` + `promotion-decision-packet.md` (ladder + policy anchored) |
| `GOBLIN-P11` | Governed ML And Self-Learning | `GOBLIN-P10` | `Goblin/contracts/model-registry.md` |
| `GOBLIN-P12` | Knowledge Store, Vector Memory, And Agentic Layer | `GOBLIN-P11` | `Goblin/contracts/knowledge-lineage.md` |
| `GOBLIN-P13` | Operational Inventory And Gap Analysis | `GOBLIN-P12` | `Goblin/reports/existing_goblin_coverage.md` |
| `GOBLIN-P14` | Session-Aware Run Logging | `GOBLIN-P13` | `Goblin/contracts/run-record.md` |
| `GOBLIN-P15` | Clean-Room Rules And Baseline Scenarios | `GOBLIN-P13` | `Goblin/contracts/clean-room-rules.md` + `Goblin/reports/baseline_scenarios.md` |
| `GOBLIN-T1` | Operator Identity Takeover | `GOBLIN-P15` | Goblin-first operator docs and CLI messaging |
| `GOBLIN-T2` | Compatibility Bridge | `GOBLIN-T1` | `src/goblin/` compatibility namespace wrappers |
| `GOBLIN-T3` | Runtime Namespace Migration | `GOBLIN-T2` | Goblin-first package identity and entrypoints |
| `GOBLIN-T4` | Clean Takeover Completion | `GOBLIN-T3` | deprecation path and migration completion evidence |

## Dependency Note: P14 and P15

P14 and P15 both depend on P13 only. They may be executed in parallel or in either order.

## Dependency Note: P06 and P07

P06 and P07 both depend on P05 only. They may be authored in parallel or in either order. P06 incident closure packets consume P07 outputs (bundle identity, ladder state), so P07 should be authored before P06 is fully implemented. In practice: execute P07 first or alongside P06.
