# Goblin Status

- Generated UTC: `2026-04-14T19:50:53.048207Z`
- Current phase: `none`
- Ready phases: `none`
- Blocked phases: `none`

## Companion Tracking

- Implementation reality: `Goblin/IMPLEMENTATION_TRACKER.md`
- Maturity model: `Goblin/MATURITY.md`
- Evolution record: `Goblin/EVOLUTION.md`
- Future rename path: `Goblin/TAKEOVER_PLAN.md`

## Operating Rule

- Work one phase at a time in sequence.
- When a phase reaches its exit criteria, update the tracking documents and stop for explicit user approval before starting the next phase.

## Phase Counts
- `completed`: 13

## Latest Activity
- `2026-04-20`: ML-P2 evaluation tools complete (commit `8f0d15a`). New tools: `tools/run_p2_eval.py` (holdout eval pipeline — BCa moving-block bootstrap, Bonferroni 4-test, Q1 fragile rule, GO/CONDITIONAL/NO_GO verdict rendering), `tools/log_p2_prediction.py` (R4-11 predictions logger for midpoint/trigger phases), `tools/run_p2_insample_eval.py` (purged walk-forward CV on in-sample rows 0:155775). New tests: 52 (33 in `test_p2_eval.py`, 19 in `test_log_p2_prediction.py`). Sealed holdout HARD_CAP still 0/2 used. Next step: run `tools/run_p2_insample_eval.py` to produce first non-error PF, then log R4-11 midpoint prediction, then run holdout ceremony.
- `2026-04-20`: ML-P2.0 pre-registration scaffolding (EX-1 through EX-10) complete. Commits `8747d45` → `27d1bd6` → `cca5cdd`. Three pre-registration decision-log entries (DEC-ML-2.0-CANDIDATES, DEC-ML-2.0-TARGET, DEC-ML-1.6b-A1-AUTHORIZATION) approved by owner and locked into `Goblin/decisions/ml_decisions.jsonl` (9 total entries, all schema-validated). Full EX-10 E2E rehearsal on synthetic data PASSED 6/6 steps: regime coverage, predictions log, ceremony happy-path (INITIATED→COMPLETED + plaintext shredded), ceremony abort-path (INITIATED→ABORTED), hard-cap enforcement (refused at HARD_CAP=2), decision-log schema validation. Report at `Goblin/reports/ml/p2_0_rehearsal_report.json`. Real holdout (HARD_CAP) unaffected: 0 of 2 decryption events used. 4 new tests in `tests/test_p20_rehearsal.py`. Test suite: 628 passing + 4 rehearsal tests via subprocess = effectively 632. HITL gate EX-10 owner-approved; proceeding to ML-P2 implementation is now unblocked pending EX-11 completion.
- `2026-04-20`: ML-P1.7 (Plan Hardening) complete. Added `tools/verify_decision_log_schema.py` (with explicit grandfather list for `DEC-ML-1.6.0-CANDIDATES`), `tools/verify_dataset_sha.py` (pinned SHA `7875ba5a…`), and `src/agentic_forex/governance/locked_benchmark.py` with case/whitespace/JSON-embedding guard for `AF-CAND-0263`. New CI lanes: `.github/workflows/ml-phase-gates.yml` (7 jobs incl. append-only check, schema check, dataset SHA pin, holdout key audit) and `.github/workflows/holdout-access.yml`. Glossary extended with BH-FDR, MDE, σ_PF, PSI, Decision Log, Effect-size floor, Sealed Holdout. Test suite: 541 total (was 463). Sealed holdout untouched; HITL re-gate (ML-P2.0) intentionally NOT run.
- `2026-04-20`: ML-P1.6b (Sequential Features Probe) complete. Verdict: `p2_proceed_unchanged`. Mean Δ-PF lift = +0.0041 over 6 surviving non-fragile candidates (4.1% of 0.10 PF target, p=0.2387 one-sided). All 6 sequential features stationary (ADF + KPSS); zero rejected by BH-FDR at q=0.10. Regime non-negativity 6/6, cost persistence at 1 pip 6/6. Sequential features will NOT be added to ML-P2 architecture. Report: `Goblin/reports/ml/p1_6b_sequential_probe.json`. Decision log entry: `DEC-ML-1.6b-COMPLETE`.
- `2026-04-20`: ML-P1.6 (Baseline Comparison) complete. Verdict: `conditional`. Median PF lift +0.0506 (~5.5× the 0.0083 effect-size floor) on 11 stratified candidates; 11/11 above floor; 11/11 cost-persistent at +1.0 pip. Regime gate: 5/11 fragile (0716, 0738, 0739, 0009, 0001), 6/11 surviving (0734, 0322, 0323, 0007, 0002, 0290). Surviving subset carried forward to 1.6b. Report: `Goblin/reports/ml/p1_6_baseline_comparison.json`. Sealed holdout created: `Goblin/holdout/ml_p2_holdout.parquet.enc` (key outside repo at `~/.goblin/holdout_keys/`).
- `2026-04-20`: ML-P1.6.0 (Variance Pilot) complete. σ_PF=0.0083 measured across 10 seeds × 3 candidates (locked XGB hparams). Effect-size floor = MDE = 0.0083 PF. Locked into `config/eval_gates.toml [ml_variance_pilot]`. Decision log initialized at `Goblin/decisions/ml_decisions.jsonl`.
- `2026-04-17`: S1-P03 started. `InpShadowModeOnly` set to `false` in packet EA. `goblin-live-attach` run against `AF-CAND-0733-limited-demo-20260414` bundle; compiled successfully (build hash `6CF531...`). Live attach manifest written at `ladder_state: limited_demo`, `lot_mode: active_demo`. Next: attach EA in MT5 on EURUSD M1, enable Algo Trading, begin collecting real demo trade evidence.
- `2026-04-17`: S1-P02 complete. Shadow week ran Apr 15–17: 208 signals over 2 trading days, 0 real orders (shadow mode confirmed). All 4 artifact types collected (attach manifest, heartbeat, runtime summary, signal trace). EA observability (Print/Comment) added to generator template and deployed EA.
- `2026-04-14`: Shadow-only EA mode implemented (`InpShadowModeOnly`), operator CLI commands added (`goblin-live-attach`, `goblin-live-heartbeat`, `goblin-live-session-end`), AF-CAND-0733 packet updated with shadow guard + output paths.

## Phase Table

| Phase | Status | Owner | Last Checkpoint | Resume | Blockers |
| --- | --- | --- | --- | --- | --- |
| `GOBLIN-P00` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P00\goblin-p00-foundation.json` | `goblin goblin-phase-update --phase-id GOBLIN-P00 --status in_progress` | none |
| `GOBLIN-P01` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P01\goblin-p01-truth-stack-controls.json` | `goblin goblin-phase-update --phase-id GOBLIN-P01 --status in_progress` | none |
| `GOBLIN-P02` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P02\goblin-p02-provenance-registry.json` | `goblin goblin-phase-update --phase-id GOBLIN-P02 --status in_progress` | none |
| `GOBLIN-P03` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P03\goblin-p03-time-session-normalization-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P03 --status in_progress` | none |
| `GOBLIN-P04` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P04\goblin-p04-mt5-certification-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P04 --status in_progress` | none |
| `GOBLIN-P05` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P05\goblin-p05-live-demo-observability-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P05 --status in_progress` | none |
| `GOBLIN-P06` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P06\goblin-p06-incident-system-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P06 --status in_progress` | none |
| `GOBLIN-P07` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P07\goblin-p07-release-control-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P07 --status in_progress` | none |
| `GOBLIN-P08` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P08\goblin-p08-investigation-framework-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P08 --status in_progress` | none |
| `GOBLIN-P09` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P09\goblin-p09-strategy-governance-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P09 --status in_progress` | none |
| `GOBLIN-P10` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P10\goblin-p10-portfolio-and-promotion-controls-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P10 --status in_progress` | none |
| `GOBLIN-P11` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P11\goblin-p11-governed-ml-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P11 --status in_progress` | none |
| `GOBLIN-P12` | `completed` | `GoblinOrchestrator` | `Goblin\checkpoints\GOBLIN-P12\goblin-p12-knowledge-and-agent-layer-complete.json` | `goblin goblin-phase-update --phase-id GOBLIN-P12 --status in_progress` | none |
