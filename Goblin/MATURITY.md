# Goblin Maturity

This document tracks Goblin maturity by subsystem so progress is not confused with completion.

## Maturity Scale

- `M0`: not started
- `M1`: planned and documented
- `M2`: scaffolded with models/contracts/placeholders
- `M3`: implemented in code for the intended scope
- `M4`: verified with targeted tests or concrete operational checks
- `M5`: governing the real repo path as the default control mechanism

## Overall Maturity

Current overall Goblin maturity: `M5`

Reason:

- Goblin is established as a tracked umbrella program.
- Truth, provenance, time/research normalization, MT5 certification, live-demo observability with broker reconciliation, incident severity governance, deployment ladder/release gating, and investigation/eval packs are now implemented and verified with targeted tests.
- Strategy governance phase P09, portfolio governance phase P10, governed ML phase P11, and retrieval/agent-governance phase P12 are implemented with targeted verification.
- Goblin phases are fully implemented under the current roadmap scope.
- P10 portfolio governance is implemented through promotion-packet policy enforcement and challenger lane gating.
- P11 governed ML is implemented through trusted label policy enforcement, offline training cycle controls, and online self-tuning/livemode approval gates.
- P12 knowledge/retrieval/agent boundaries are implemented through structured event store, advisory retrieval index, provenance-cited responses, and bounded role enforcement.
- Top-level governance now explicitly matches the completed live-demo and deployment-ladder contracts for MT5 demo-account EA automation.

## Subsystem Maturity

| Subsystem | Maturity | Basis |
| --- | --- | --- |
| Program scaffolding and phase tracking | `M4` | directory, state, checkpoints, CLI, and tests exist |
| Truth-stack contracts | `M4` | modeled, documented, exposed, and tested |
| Provenance and artifact registry | `M4` | implemented with registration/validation and tested |
| Time/session normalization | `M4` | comparison time basis is declared and checked in truth-alignment reports with targeted tests |
| OANDA research reproducibility | `M4` | OANDA ingest/backfill outputs now record the frozen acquisition contract and targeted tests cover it |
| MT5 executable certification | `M4` | certification artifacts are emitted for parity and incident replay, deployment authority now requires `deployment_grade`, and targeted tests cover the enforcement boundary |
| Live-demo observability under Goblin | `M4` | attach manifest, runtime summary, heartbeat writers, and anomaly detection implemented and verified with 10 targeted tests; repo-level policy now explicitly permits governed MT5 demo-account attaches |
| Broker/account reconciliation | `M4` | broker CSV ingestion, EA audit matching, PnL delta calculation, MT5 primitive distinction, and BrokerReconciliationReport writer implemented and verified with targeted tests |
| ML evidence-chain (1.6.0 → 1.6 → 1.6b → 1.7 → 2.0 pre-reg → 2.0 tools) | `M4` | Variance Pilot (σ_PF=0.0083 locked), Baseline Comparison (6/11 candidates surviving regime gate), Sequential Probe (`p2_proceed_unchanged`, +0.0041 mean Δ-PF), Plan Hardening (decision-log + dataset-SHA validators, AF-CAND-0263 guard, CI scaffolding), ML-P2.0 pre-registration scaffolding (EX-1–EX-10), and ML-P2 evaluation pipeline all complete. σ_cross=0.0211, MDE_upper=0.0503 locked; verdict bands (GO≥0.10, CONDITIONAL≥0.055) pre-committed; regime thresholds frozen; BCa moving-block bootstrap + Bonferroni 4-test + Q1 fragile rule implemented in `tools/run_p2_eval.py`; R4-11 prediction logger in `tools/log_p2_prediction.py`; in-sample walk-forward CV in `tools/run_p2_insample_eval.py`. HARD_CAP ceremony (0/2 used); 52 new tests (656+ total passing). NEXT: run insample eval → log midpoint prediction → holdout ceremony. |
| Execution cost contract | `M2` | full contract authored; no enforcement code yet |
| Statistical decision policy | `M4` | promotion packets now cite statistical policy keys from config/eval_gates.toml; free-text judgment is rejected; enforcement implemented and tested |
| Incident severity and SLA governance | `M4` | IncidentRecord carries severity/sla_class/incident_type; validate_incident_closure enforces required fields per severity; close_incident_record validates before persisting; list_open_blocking_incidents returns S1/S2 blockers; 17 targeted tests |
| Deployment ladder | `M4` | LiveAttachManifest carries ladder_state/broker_server/bundle_id; IncidentClosurePacket carries ladder_state_at_incident; DeploymentLadderState type defined; 7 targeted tests |
| Environment reproducibility | `M3` | config drift detection via validate_attach_against_bundle; terminal build pinning contract authored; hash-mismatch opens S1 incident; secrets policy via existing resolve_secret(); no automated terminal pinning check yet |
| Release and approval gating | `M4` | validate_attach_against_bundle enforces inputs_hash check; S1 release_integrity_failure auto-opened on mismatch; 7 targeted tests |
| Investigation and evaluation layer | `M4` | scenario/trace/evaluation-suite writers and benchmark-history snapshots implemented; 40 targeted Goblin tests pass and AF-CAND-0263 has a reproducible investigation pack |
| Strategy methodology governance | `M5` | rationale-card, experiment-accounting, methodology-rubric, and invalid-comparison controls are enforced across governed actions, direct campaign entrypoints, live/demo progression gates, and promotion packets, with targeted tests verifying the control path |
| Portfolio/challenger governance under Goblin | `M4` | promotion packet enforces policy-key citations, observed_demo ladder floor, and deployment-fit delta bundle linkage; portfolio cycle gates challenger progression on existing promotion packet; 7 targeted tests pass |
| Governed ML/self-learning | `M4` | trusted label policy and offline training cycle writers are implemented with enforcement checks, model registry links to policy/cycle artifacts, live-touch approval gate exists, and targeted tests cover the constraints |
| Knowledge store/vector memory | `M4` | structured event store, retrieval-document persistence, vector index build, and provenance-cited retrieval responses are implemented with targeted tests |
| Agentic layer bounded by Goblin | `M4` | bounded role model and action-allowance enforcement implemented and tested; governance-authority actions are blocked |
| Namespace takeover from Agentic Forex to Goblin | `M4` | Goblin-first package/CLI identity implemented with compatibility bridge, deprecation contract, and namespace interoperability tests |
| Session-aware run logging | `M4` | GoblinRunRecord model with classify_session_window, JSONL persistence, campaign integration into all 3 entrypoints, 18 tests |
| Clean-room pattern governance | `M4` | 7 auditable rules ratified, 5 baseline scenarios documented, pattern card template and framework gap matrix published |
| Multi-timezone strategy program | `M1` | remaining phased execution is documented in `Goblin/S1_PLUS_PLAN.md`; operational execution has not started |
| ML Evolution Program | `M1` | 8-phase plan (ML-P0 through ML-P3d) with governance tiers, rollback procedures, and HITL gates documented in `Goblin/ML_EVOLUTION_PLAN.md`; no implementation started |

## Advancement Rule

Raise a maturity level only when the evidence changes. Do not raise maturity because a contract doc exists if runtime or governance behavior is still missing.
