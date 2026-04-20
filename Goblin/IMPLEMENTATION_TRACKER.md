# Goblin Implementation Tracker

This document answers a specific question: what in Goblin is actually implemented, what is partial, what is scaffold only, and what is still not started.

Status meanings:

- `implemented`: delivered in code or authoritative docs and verified enough to support the phase claim
- `partial`: meaningful implementation exists, but the phase exit criteria are not yet satisfied
- `scaffold_only`: models, contracts, placeholders, or docs exist, but the operational behavior is not implemented
- `not_started`: phase intent exists only in the roadmap/state plan

## Phase-Level Tracker

| Phase | State File Status | Implementation Reality | What Exists | What Is Still Missing |
| --- | --- | --- | --- | --- |
| `GOBLIN-P00` | `completed` | `implemented` | Goblin program directory, phase/state/checkpoint system, templates, ADR scaffold, CLI alias plan, operator/orchestrator split docs | none for phase intent |
| `GOBLIN-P01` | `completed` | `implemented` | four-channel truth models, comparison contracts, truth-stack docs, truth alignment report builder, Goblin truth CLI surfaces | broader enforcement into all legacy workflows remains future work, but phase intent is satisfied |
| `GOBLIN-P02` | `completed` | `implemented` | artifact provenance models, evidence-channel tagging support, channel-owned indexes, artifact registration/validation helpers, provenance docs | full repo-wide migration of every legacy path is ongoing later work, but Goblin provenance layer exists |
| `GOBLIN-P03` | `completed` | `implemented` | default research-data contract builder, default time/session contract builder, truth-alignment time-basis enforcement, OANDA ingest provenance freezing, contract docs, data-quality gates | none for the phase exit criteria |
| `GOBLIN-P04` | `completed` | `implemented` | Goblin MT5 certification reports are written for parity and incident replay runs, tick provenance is derived from tester mode, incident replay trust now requires a passed baseline harness, and official parity authority is gated on `deployment_grade` certification | none for the phase exit criteria |
| `GOBLIN-P05` | `completed` | `implemented` | live attach manifest, runtime summary, heartbeat writers, broker CSV ingestion with MT5 primitive distinction, trade reconciliation pipeline, anomaly detection, execution-cost-contract, statistical-decision-policy, expanded broker-reconciliation contract, and 10 targeted tests | broader operational wiring into live MT5 terminal workflows remains future work, but all phase exit criteria are satisfied |
| `GOBLIN-P06` | `completed` | `implemented` | IncidentRecord carries severity/sla_class/incident_type/ladder_state_at_incident/deployed_bundle_id; validate_incident_closure enforces required closure evidence per S1/S2/S3; close_incident_record validates before persisting; list_open_blocking_incidents returns open S1/S2 blocking incidents; INCIDENT_RESPONSE.md runbook updated; 17 targeted tests | none for phase exit criteria |
| `GOBLIN-P07` | `completed` | `implemented` | LiveAttachManifest carries ladder_state/broker_server/bundle_id; IncidentClosurePacket carries deployed_bundle_id/ladder_state_at_incident; validate_attach_against_bundle checks inputs_hash and opens S1 release_integrity_failure on mismatch; RELEASE_AND_ROLLBACK.md runbook updated; 7 targeted tests | none for phase exit criteria |
| `GOBLIN-P08` | `completed` | `implemented` | investigation scenario/trace/evaluation-suite models, benchmark-history writer, `build_incident_investigation_pack`, CLI parser coverage, and a reproducible AF-CAND-0263 serious-incident pack under `Goblin/reports/investigations/` | none for the phase exit criteria |
| `GOBLIN-P09` | `completed` | `implemented` | methodology rubric contract and audit artifacts, strategy rationale card controls, experiment-accounting budget gates, invalid-comparison enforcement in `compare_experiments`, direct campaign entrypoint governance gates (`run_next_step`, `run_governed_loop`, `run_program_loop`, `run_autonomous_manager`, `run_bounded_campaign`), candidate-level live/demo gating (`publish_candidate`, `generate_mt5_packet`, `write_live_attach_manifest`), and promotion-packet search-bias narrative wiring | none for phase exit criteria |
| `GOBLIN-P10` | `completed` | `implemented` | promotion packet enforces statistical-policy key citations, deployment ladder state, and material deployment-fit delta bundle linkage; portfolio cycle gates challenger lane on having an existing promotion packet; locked benchmark candidate reference auto-surfaced in each cycle; 7 new targeted tests pass | none for phase exit criteria |
| `GOBLIN-P11` | `completed` | `implemented` | trusted label policy artifacts with ambiguity-rejection gate, offline training cycle artifacts with holdout and MT5-live-touch checks, model registry linkage to policy/cycle artifacts, and ML governance enforcement gate blocking online self-tuning and unapproved live-touching models | broader model-family expansion beyond the P11 scope remains future work |
| `GOBLIN-P12` | `completed` | `implemented` | structured knowledge event store, retrieval-document persistence, deterministic vector-memory index, provenance-cited retrieval responses, and bounded agent-role enforcement controls with targeted tests | broader semantic ranking sophistication beyond deterministic token overlap remains future work |
| `GOBLIN-P13` | `completed` | `implemented` | Operational inventory with 8 subsystem rows and 4 gap analyses at `Goblin/reports/existing_goblin_coverage.md` | none for phase intent |
| `GOBLIN-P14` | `completed` | `implemented` | GoblinRunRecord model, classify_session_window (5 windows), start/finalize helpers, JSONL writer, integration into portfolio.py/program_loop.py/autonomous_manager.py, run-record contract, 18 tests | none for phase intent |
| `GOBLIN-P15` | `completed` | `implemented` | 7 clean-room rules at `Goblin/contracts/clean-room-rules.md`, 5 baseline scenarios, pattern card template, framework gap matrix with 10 capability rows | none for phase intent |
| `GOBLIN-T1` | `completed` | `implemented` | Goblin-first operator CLI messaging and takeover tracking updates | none for phase intent |
| `GOBLIN-T2` | `completed` | `implemented` | `src/goblin/` compatibility namespace and CLI forwarding wrappers | none for phase intent |
| `GOBLIN-T3` | `completed` | `implemented` | project/package identity and script entrypoints switched to Goblin-first | none for phase intent |
| `GOBLIN-T4` | `completed` | `implemented` | compatibility-only legacy namespace declaration and takeover completion evidence report | none for phase intent |

## Cross-Cutting System Tracker

| Surface | Current Status | Notes |
| --- | --- | --- |
| Goblin program scaffolding | `implemented` | `/Goblin` exists with roadmap, status, state, phases, contracts, checkpoints, templates, runbooks |
| Goblin CLI surfaces | `implemented` | init/status/phase/checkpoint plus evidence/control helper commands were added |
| Four-channel truth stack | `implemented` | modeled and documented |
| Provenance registry and channel indexes | `implemented` | registration and validation helpers exist |
| Time/session normalization | `implemented` | comparison time basis is now declared in truth reports and mismatches are surfaced |
| MT5 executable certification | `implemented` | certification artifacts are written, parity authority now requires `deployment_grade`, and incident replay harness trust is separated from candidate alpha claims |
| Live-demo observability | `implemented` | attach manifest, runtime summary, heartbeat writers, anomaly detection, shadow-mode EA guard (`InpShadowModeOnly`), and operator CLI commands (`goblin-live-attach`, `goblin-live-heartbeat`, `goblin-live-session-end`) all implemented and tested |
| Demo-account MT5 automation policy alignment | `implemented` | top-level repo governance now explicitly allows governed MT5 demo-account EA automation under live-demo, bundle, and ladder controls while still forbidding real-money automation |
| Broker/account reconciliation | `implemented` | broker CSV ingestion, EA audit comparison, and BrokerReconciliationReport writer implemented and tested |
| Incident severity and SLA governance | `implemented` | IncidentRecord carries severity/sla_class; validate_incident_closure enforces field requirements; list_open_blocking_incidents returns S1/S2 blockers; close_incident_record validates before persisting |
| Deployment ladder and release gating | `implemented` | LiveAttachManifest carries ladder_state and bundle_id; validate_attach_against_bundle enforces hash checks; release_integrity_failure S1 opened automatically on mismatch |
| Investigation/eval framework | `implemented` | reproducible investigation packs now persist scenario JSONs, trace JSONs, evaluation suites, and frozen benchmark history; targeted tests pass and AF-CAND-0263 has a real investigation pack |
| Search-bias governance | `implemented` | family-level experiment accounting ledgers, strategy rationale cards, methodology-rubric audits, and invalid-comparison rules are enforced; legacy campaign entrypoints and live/demo candidate progression paths now run through strategy-governance gates; promotion packets carry search-bias governance evidence |
| Governed ML | `implemented` | trusted label policy writer, offline training cycle writer, and model-governance enforcement are implemented and covered by targeted tests |
| Retrieval/vector memory | `implemented` | retrieval documents, index build, and provenance-cited advisory retrieval responses are implemented and tested |
| Namespace takeover to Goblin | `implemented` | Goblin namespace package, CLI bridge, pyproject identity migration, compatibility test coverage, and takeover completion report are in place |
| Session-aware run logging | `implemented` | GoblinRunRecord with session_window derived from classify_session_window(); integrated into all 3 campaign entrypoints; append-only JSONL persistence; 18 tests |
| Multi-timezone strategy program | `planned` | Post-takeover program; remaining execution is now captured in `Goblin/S1_PLUS_PLAN.md`, but operational execution has not started |
| Shadow-only EA mode | `implemented` | `InpShadowModeOnly` input added to EA generator template and AF-CAND-0733 packet; guards `trade.Buy()`/`trade.Sell()` while preserving signal generation, trace writing, and runtime summary; output paths (`InpSignalTraceRelativePath`, `InpRuntimeSummaryRelativePath`) populated for AF-CAND-0733 |
| EA observability (Print/Comment) | `implemented` | `Print()` logging at every decision point (init, deinit, bar processing, spread blocks, hour filter, signal fire, shadow order) and on-chart `Comment()` overlay showing bars/hour/signals/orders; added to both generator template and AF-CAND-0733 deployed EA |
| S1-P02 shadow-only attach | `implemented` | AF-CAND-0733 shadow week completed Apr 15–17: 208 signals across 2 trading days (116 long, 92 short), 0 real orders, 0 failures; all 4 governed artifact types collected; auto-deploy/compile baked into `goblin-live-attach` |
| S1-P03 limited-demo attach | `in_progress` | S1-P03 started 2026-04-17: `InpShadowModeOnly=false` set in packet EA; `goblin-live-attach` against `AF-CAND-0733-limited-demo-20260414` compiled and manifested at `ladder_state: limited_demo`; pending MT5 manual re-attach and first real demo trade evidence |
| ML Evolution Program | `awaiting_owner_decision` | Bundle A (ML-P0) + evidence-first phases ML-P1.6.0/1.6/1.6b/1.7 + ML-P2.0 pre-registration scaffolding (EX-1–EX-10) + ML-P2 evaluation pipeline + **holdout ceremony all complete as of 2026-04-20**. Verdict: NO_GO. Aggregate primary PF lift +0.0528 (below CONDITIONAL floor 0.055); BCa 95% CI [-0.027, +0.261] crosses zero. Q1 fragile cohort all positive. Midpoint prediction was correct (NO_GO). Sealed holdout HARD_CAP: 2/2 used. Predictions log: 2 entries (PRED-ML-2.0-MIDPOINT-1, PRED-ML-2.0-TRIGGER-1). AWAITING OWNER DECISION: ML-P3 (architecture revision) or halt. Original status: Bundle A (ML-P0) + evidence-first phases ML-P1.6.0/1.6/1.6b/1.7 + ML-P2.0 pre-registration scaffolding (EX-1–EX-10) + ML-P2 evaluation pipeline (EX-11 tracking + P2 tools) all complete as of 2026-04-20. σ_PF=0.0083; 6/11 candidates surviving regime gate; sequential features did not clear bar; ML-P2 to proceed with original architecture. Pre-registration decisions locked: DEC-ML-2.0-CANDIDATES (n=6 primary cohort), DEC-ML-2.0-TARGET (GO≥0.10 PF, CONDITIONAL≥0.055 PF, Q1 fragile rule, BCa bootstrap, Bonferroni 4-test family), DEC-ML-1.6b-A1-AUTHORIZATION (sequential CNN excluded). E2E rehearsal PASSED 6/6 on synthetic data. ML-P2 tools added (commit `8f0d15a`): `tools/run_p2_eval.py` (holdout eval + BCa + Bonferroni + Q1 + verdict), `tools/log_p2_prediction.py` (R4-11 predictions logger), `tools/run_p2_insample_eval.py` (in-sample walk-forward CV). New tests: +52 (33 verdict/bootstrap/Q1 tests + 19 prediction-log tests). Total suite: 656+ passing. Sealed holdout HARD_CAP: 0/2 used. NEXT: run `tools/run_p2_insample_eval.py` → log R4-11 midpoint prediction → run holdout ceremony. |

## Update Rule

Whenever Goblin work changes implementation reality, this tracker must be updated in the same change.
