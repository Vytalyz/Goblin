from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.approval.models import ApprovalRecord
from agentic_forex.approval.service import publish_candidate, record_approval
from agentic_forex.backtesting.benchmark import run_scalping_benchmark
from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.campaigns import (
    run_autonomous_manager,
    run_bounded_campaign,
    run_governed_loop,
    run_next_step,
    run_portfolio_cycle,
    run_program_loop,
)
from agentic_forex.config import load_settings
from agentic_forex.corpus.catalog import catalog_corpus
from agentic_forex.experiments import (
    compare_experiments,
    explore_day_trading_candidates,
    explore_scalping_candidates,
    iterate_scalping_target,
    refine_day_trading_target,
    scan_day_trading_behaviors,
)
from agentic_forex.forward import run_shadow_forward
from agentic_forex.goblin import (
    ArtifactProvenance,
    build_deployment_bundle,
    build_incident_investigation_pack,
    close_incident_record,
    create_goblin_checkpoint,
    default_approval_boundaries,
    get_goblin_program_status,
    initialize_goblin_program,
    open_incident_record,
    run_broker_reconciliation,
    update_goblin_phase,
    validate_attach_against_bundle,
    write_candidate_scorecard,
    write_experiment_accounting_ledger,
    write_live_attach_manifest,
    write_runtime_heartbeat,
    write_runtime_summary,
    write_strategy_rationale_card,
)
from agentic_forex.goblin.evidence import (
    artifact_by_id,
    build_default_research_data_contract,
    build_default_time_session_contract,
    build_truth_alignment_report,
    latest_registered_artifact,
    register_artifact,
    validate_artifact_provenance,
)
from agentic_forex.goblin.models import (
    DeploymentBundle,
    LiveAttachManifest,
    RuntimeHeartbeat,
    RuntimeSummary,
)
from agentic_forex.governance import CampaignSpec
from agentic_forex.governance.incident import run_production_incident_analysis
from agentic_forex.industry.report import generate_industry_report
from agentic_forex.llm import MockLLMClient, OpenAIClient
from agentic_forex.market_data.ingest import (
    backfill_oanda_history,
    fetch_oanda_candles,
    ingest_market_csv,
    ingest_mt5_parity_csv,
    ingest_oanda_json,
)
from agentic_forex.market_data.qa import assess_market_data_quality
from agentic_forex.ml.train import train_models
from agentic_forex.mt5.service import (
    cleanup_mt5_experts,
    deploy_and_compile_candidate_ea,
    generate_mt5_packet,
    run_mt5_incident_replay,
    run_mt5_manual_test,
    validate_mt5_practice,
)
from agentic_forex.nodes import build_tool_registry
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.operator import (
    audit_candidate_branches,
    audit_candidate_window_density,
    build_queue_snapshot,
    export_operator_state,
    inspect_governed_action,
    run_governed_action,
    sync_codex_capabilities,
    validate_operator_contract,
)
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.policy.parity_scope import build_parity_scope_audit
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.utils.io import read_json
from agentic_forex.utils.secrets import write_windows_credential
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, DiscoveryRequest, MT5ValidationRequest, StrategySpec


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--project-root",
        default=argparse.SUPPRESS,
        help="Absolute path to the Goblin project root.",
    )
    common.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help="Optional TOML config path.",
    )
    parser = argparse.ArgumentParser(description="Goblin root-level research platform")
    parser.add_argument("--project-root", help="Absolute path to the Goblin project root.")
    parser.add_argument("--config", help="Optional TOML config path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog-corpus", parents=[common])
    catalog.add_argument("--mirror-path", required=True)

    ingest = subparsers.add_parser("ingest-market", parents=[common])
    source_group = ingest.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--input-csv")
    source_group.add_argument("--oanda-json")
    source_group.add_argument("--fetch-oanda", action="store_true")
    source_group.add_argument("--backfill-oanda", action="store_true")
    source_group.add_argument("--mt5-audit-csv")
    ingest.add_argument("--instrument")
    ingest.add_argument("--granularity")
    ingest.add_argument("--count", type=int)
    ingest.add_argument("--start")
    ingest.add_argument("--end")
    ingest.add_argument("--chunk-size", type=int, default=5000)

    qa_market = subparsers.add_parser("qa-market", parents=[common])
    qa_market.add_argument("--instrument")
    qa_market.add_argument("--granularity")
    qa_market.add_argument("--parquet-path")

    calendar = subparsers.add_parser("ingest-calendar", parents=[common])
    calendar.add_argument("--input-csv", required=True)

    discover = subparsers.add_parser("discover", parents=[common])
    discover.add_argument("--question", required=True)
    discover.add_argument("--family")
    discover.add_argument("--mirror-path", required=True)
    discover.add_argument("--workflow", default=None)

    explore = subparsers.add_parser("explore-scalping", parents=[common])
    explore.add_argument("--mirror-path")
    explore.add_argument("--count", type=int, default=4)
    explore.add_argument("--max-sources", type=int, default=5)

    explore_day = subparsers.add_parser("explore-day-trading", parents=[common])
    explore_day.add_argument("--mirror-path")
    explore_day.add_argument("--count", type=int, default=3)
    explore_day.add_argument("--max-sources", type=int, default=5)
    explore_day.add_argument("--family", default=None)
    explore_day.add_argument("--reference-candidate", default=None)
    explore_day.add_argument("--max-materialized", type=int, default=None)

    scan_day = subparsers.add_parser("scan-day-trading-behaviors", parents=[common])
    scan_day.add_argument("--mirror-path")
    scan_day.add_argument("--max-sources", type=int, default=5)
    scan_day.add_argument("--family", default=None)
    scan_day.add_argument("--reference-candidate", default=None)
    scan_day.add_argument("--refresh-candidates", action="store_true")
    scan_day.add_argument("--max-materialized", type=int, default=None)

    refine_day = subparsers.add_parser("refine-day-trading-target", parents=[common])
    refine_day.add_argument("--target-id", required=True)
    refine_day.add_argument("--family-override", default=None)

    iterate = subparsers.add_parser("iterate-scalping-target", parents=[common])
    iterate.add_argument("--baseline-id", required=True)
    iterate.add_argument("--target-id", required=True)

    spec = subparsers.add_parser("spec-candidate", parents=[common])
    spec.add_argument("--candidate-json", required=True)

    backtest = subparsers.add_parser("backtest", parents=[common])
    backtest.add_argument("--spec-json", required=True)

    train = subparsers.add_parser("train-models", parents=[common])
    train.add_argument("--spec-json", required=True)

    stress = subparsers.add_parser("stress-test", parents=[common])
    stress.add_argument("--spec-json", required=True)

    shadow_forward = subparsers.add_parser("shadow-forward", parents=[common])
    shadow_forward.add_argument("--spec-json", required=True)

    review = subparsers.add_parser("review-candidate", parents=[common])
    review.add_argument("--spec-json", required=True)
    review.add_argument("--workflow", default=None)

    benchmark = subparsers.add_parser("benchmark-scalping", parents=[common])
    benchmark_source = benchmark.add_mutually_exclusive_group(required=True)
    benchmark_source.add_argument("--candidate-json")
    benchmark_source.add_argument("--spec-json")

    compare = subparsers.add_parser("compare-experiments", parents=[common])
    compare.add_argument("--family")
    compare.add_argument("--candidate-id", action="append", dest="candidate_ids")
    compare.add_argument("--limit", type=int)

    campaign = subparsers.add_parser("run-campaign", parents=[common])
    campaign.add_argument("--campaign-id", default=None)
    campaign.add_argument("--family", default="scalping")
    campaign.add_argument("--baseline-id", required=True)
    campaign.add_argument("--target-id", action="append", dest="target_ids", required=True)
    campaign.add_argument("--max-iterations", type=int, default=None)
    campaign.add_argument("--max-new-candidates", type=int, default=None)
    campaign.add_argument("--trial-cap", type=int, default=None)
    campaign.add_argument("--note", action="append", dest="notes")

    next_step = subparsers.add_parser("run-next-step", parents=[common])
    next_step.add_argument("--campaign-id", default=None)
    next_step.add_argument("--parent-campaign-id", default=None)
    next_step.add_argument("--family", default="scalping")
    next_step.add_argument(
        "--allowed-step-type",
        action="append",
        dest="allowed_step_types",
        choices=[
            "diagnose_existing_candidates",
            "mutate_one_candidate",
            "re_evaluate_one_candidate",
            "formalize_rule_candidate",
            "generate_ea_spec",
            "compile_ea_candidate",
            "run_mt5_backtest_smoke",
            "triage_reviewable_candidate",
            "hypothesis_audit",
            "data_regime_audit",
            "data_feature_audit",
            "data_label_audit",
            "run_parity",
            "run_forward",
        ],
    )

    governed_loop = subparsers.add_parser("run-governed-loop", parents=[common])
    governed_loop.add_argument("--loop-id", default=None)
    governed_loop.add_argument("--parent-campaign-id", default=None)
    governed_loop.add_argument("--family", default="scalping")
    governed_loop.add_argument("--max-steps", type=int, default=8)
    governed_loop.add_argument(
        "--allowed-step-type",
        action="append",
        dest="allowed_step_types",
        choices=[
            "diagnose_existing_candidates",
            "mutate_one_candidate",
            "re_evaluate_one_candidate",
            "formalize_rule_candidate",
            "generate_ea_spec",
            "compile_ea_candidate",
            "run_mt5_backtest_smoke",
            "triage_reviewable_candidate",
            "hypothesis_audit",
            "data_regime_audit",
            "data_feature_audit",
            "data_label_audit",
            "run_parity",
            "run_forward",
        ],
    )

    program_loop = subparsers.add_parser("run-program-loop", parents=[common])
    program_loop.add_argument("--program-id", default=None)
    program_loop.add_argument("--parent-campaign-id", default=None)
    program_loop.add_argument("--family", default="scalping")
    program_loop.add_argument("--max-lanes", type=int, default=None)

    autonomous_manager = subparsers.add_parser("run-autonomous-manager", parents=[common])
    autonomous_manager.add_argument("--manager-run-id", default=None)
    autonomous_manager.add_argument("--program-id", default=None)
    autonomous_manager.add_argument("--parent-campaign-id", default=None)
    autonomous_manager.add_argument("--family", default="scalping")
    autonomous_manager.add_argument("--max-cycles", type=int, default=None)

    portfolio_cycle = subparsers.add_parser("run-portfolio-cycle", parents=[common])
    portfolio_cycle.add_argument("--cycle-id", default=None)
    portfolio_cycle.add_argument("--slot", default=None)
    portfolio_cycle.add_argument("--all-slots", action="store_true")

    publish = subparsers.add_parser("publish-candidate", parents=[common])
    publish.add_argument("--candidate-id", required=True)

    approve = subparsers.add_parser("approve", parents=[common])
    approve.add_argument("--candidate-id", required=True)
    approve.add_argument("--stage", required=True)
    approve.add_argument("--decision", required=True, choices=["approve", "reject"])
    approve.add_argument("--approver", required=True)
    approve.add_argument("--rationale", required=True)

    packet = subparsers.add_parser("generate-mt5-packet", parents=[common])
    packet.add_argument("--candidate-id", required=True)

    validate = subparsers.add_parser("validate-mt5-practice", parents=[common])
    validate.add_argument("--candidate-id", required=True)
    validate.add_argument("--audit-csv")

    manual_mt5 = subparsers.add_parser("run-mt5-manual-test", parents=[common])
    manual_mt5.add_argument("--candidate-id", required=True)
    manual_mt5.add_argument("--deposit", type=float, default=None)
    manual_mt5.add_argument("--leverage", type=float, default=None)
    manual_mt5.add_argument("--fixed-lots", type=float, default=None)
    manual_mt5.add_argument("--auto-scale-lots", action="store_true")
    manual_mt5.add_argument("--min-lot", type=float, default=0.01)
    manual_mt5.add_argument("--lot-step", type=float, default=0.01)
    manual_mt5.add_argument("--tester-mode", default=None)

    incident_replay = subparsers.add_parser("run-mt5-incident-replay", parents=[common])
    incident_replay.add_argument("--candidate-id", required=True)
    incident_replay.add_argument("--window-start", required=True)
    incident_replay.add_argument("--window-end", required=True)
    incident_replay.add_argument("--incident-id", default=None)
    incident_replay.add_argument("--deposit", type=float, default=None)
    incident_replay.add_argument("--leverage", type=float, default=None)
    incident_replay.add_argument("--fixed-lots", type=float, default=None)
    incident_replay.add_argument("--tester-mode", default=None)

    production_incident = subparsers.add_parser("run-production-incident", parents=[common])
    production_incident.add_argument("--candidate-id", default="AF-CAND-0263")
    production_incident.add_argument("--incident-id", default=None)
    production_incident.add_argument("--window-start", default=None)
    production_incident.add_argument("--window-end", default=None)
    production_incident.add_argument("--live-audit-csv", default=None)
    production_incident.add_argument("--mt5-replay-audit-csv", default=None)
    production_incident.add_argument("--deterministic-ledger-csv", default=None)
    production_incident.add_argument("--baseline-tester-report", default=None)
    production_incident.add_argument("--same-window-tester-report", default=None)

    audit_parity_scope = subparsers.add_parser("audit-parity-scope", parents=[common])
    audit_parity_scope.add_argument(
        "--no-write-docs",
        action="store_true",
        help="Generate the JSON report only and do not rewrite the markdown knowledge docs.",
    )

    sync_capabilities = subparsers.add_parser("sync-codex-capabilities", parents=[common])
    sync_capabilities.add_argument("--run-id", default=None)

    export_state = subparsers.add_parser("export-operator-state", parents=[common])
    export_state.add_argument("--run-id", default=None)
    export_state.add_argument("--family", default=None)

    validate_operator = subparsers.add_parser("validate-operator-contract", parents=[common])
    validate_operator.add_argument("--strict", action="store_true")

    audit_branches = subparsers.add_parser("audit-candidate-branches", parents=[common])
    audit_branches.add_argument("--candidate-id", action="append", dest="candidate_ids", required=True)
    audit_branches.add_argument("--next-family-hint", default=None)

    audit_window_density = subparsers.add_parser("audit-candidate-window-density", parents=[common])
    audit_window_density.add_argument("--candidate-id", action="append", dest="candidate_ids", required=True)
    audit_window_density.add_argument("--reference-candidate", default=None)

    queue_snapshot = subparsers.add_parser("queue-snapshot", parents=[common])
    queue_snapshot.add_argument("--family", default=None)

    governed_action = subparsers.add_parser("run-governed-action", parents=[common])
    governed_action.add_argument(
        "--action",
        required=True,
        choices=["next_step", "governed_loop", "program_loop", "autonomous_manager", "portfolio_cycle"],
    )
    governed_action.add_argument("--run-id", default=None)
    governed_action.add_argument("--family", default="scalping")
    governed_action.add_argument("--parent-campaign-id", default=None)
    governed_action.add_argument("--campaign-id", default=None)
    governed_action.add_argument(
        "--allowed-step-type",
        action="append",
        dest="allowed_step_types",
        choices=[
            "diagnose_existing_candidates",
            "mutate_one_candidate",
            "re_evaluate_one_candidate",
            "formalize_rule_candidate",
            "generate_ea_spec",
            "compile_ea_candidate",
            "run_mt5_backtest_smoke",
            "triage_reviewable_candidate",
            "hypothesis_audit",
            "data_regime_audit",
            "data_feature_audit",
            "data_label_audit",
            "run_parity",
            "run_forward",
        ],
    )
    governed_action.add_argument("--loop-id", default=None)
    governed_action.add_argument("--max-steps", type=int, default=8)
    governed_action.add_argument("--program-id", default=None)
    governed_action.add_argument("--max-lanes", type=int, default=None)
    governed_action.add_argument("--manager-run-id", default=None)
    governed_action.add_argument("--max-cycles", type=int, default=None)
    governed_action.add_argument("--cycle-id", default=None)
    governed_action.add_argument("--slot", default=None)
    governed_action.add_argument("--all-slots", action="store_true")

    inspect_action = subparsers.add_parser("inspect-governed-action", parents=[common])
    inspect_action.add_argument("--run-id", default=None)
    inspect_action.add_argument("--manifest-path", default=None)

    setup_oanda = subparsers.add_parser("setup-oanda-credential", parents=[common])
    setup_oanda.add_argument("--target", default=None)
    setup_oanda.add_argument("--username", default="api-token")

    goblin_init = subparsers.add_parser("goblin-init", parents=[common])
    goblin_init.add_argument("--refresh-docs", action="store_true")

    subparsers.add_parser("goblin-status", parents=[common])

    goblin_startup = subparsers.add_parser("goblin-startup", parents=[common])
    goblin_startup.add_argument("--focus", default=None)

    goblin_phase_update = subparsers.add_parser("goblin-phase-update", parents=[common])
    goblin_phase_update.add_argument("--phase-id", required=True)
    goblin_phase_update.add_argument(
        "--status",
        choices=[
            "not_started",
            "ready",
            "in_progress",
            "blocked",
            "verification_pending",
            "completed",
            "superseded",
            "incident_open",
        ],
        default=None,
    )
    goblin_phase_update.add_argument("--blocker", action="append", dest="blockers")
    goblin_phase_update.add_argument("--note", action="append", dest="notes")
    goblin_phase_update.add_argument("--acceptance", action="append", dest="acceptance_updates")
    goblin_phase_update.add_argument("--owner", default=None)

    goblin_checkpoint = subparsers.add_parser("goblin-checkpoint", parents=[common])
    goblin_checkpoint.add_argument("--phase-id", required=True)
    goblin_checkpoint.add_argument("--summary", required=True)
    goblin_checkpoint.add_argument("--checkpoint-id", default=None)
    goblin_checkpoint.add_argument("--authoritative-artifact", action="append", dest="authoritative_artifacts")
    goblin_checkpoint.add_argument("--regenerable-artifact", action="append", dest="regenerable_artifacts")
    goblin_checkpoint.add_argument(
        "--status",
        choices=[
            "not_started",
            "ready",
            "in_progress",
            "blocked",
            "verification_pending",
            "completed",
            "superseded",
            "incident_open",
        ],
        default=None,
    )

    goblin_register_artifact = subparsers.add_parser("goblin-register-artifact", parents=[common])
    goblin_register_artifact.add_argument(
        "--channel",
        required=True,
        choices=["research_backtest", "mt5_replay", "live_demo", "broker_account_history"],
    )
    goblin_register_artifact.add_argument("--candidate-id", required=True)
    goblin_register_artifact.add_argument("--run-id", required=True)
    goblin_register_artifact.add_argument("--artifact-origin", required=True)
    goblin_register_artifact.add_argument("--artifact-path", required=True)
    goblin_register_artifact.add_argument("--symbol", required=True)
    goblin_register_artifact.add_argument("--timezone-basis", required=True)
    goblin_register_artifact.add_argument("--terminal-id", default=None)
    goblin_register_artifact.add_argument("--terminal-build", default=None)
    goblin_register_artifact.add_argument("--broker-server", default=None)
    goblin_register_artifact.add_argument("--artifact-hash", default=None)
    goblin_register_artifact.add_argument("--authoritative", action="store_true")
    goblin_register_artifact.add_argument("--no-snapshot", action="store_true")

    goblin_validate_artifact = subparsers.add_parser("goblin-validate-artifact", parents=[common])
    goblin_validate_artifact.add_argument(
        "--channel",
        required=True,
        choices=["research_backtest", "mt5_replay", "live_demo", "broker_account_history"],
    )
    goblin_validate_artifact.add_argument("--candidate-id", required=True)
    goblin_validate_artifact.add_argument("--run-id", required=True)
    goblin_validate_artifact.add_argument("--artifact-origin", required=True)
    goblin_validate_artifact.add_argument("--artifact-path", required=True)
    goblin_validate_artifact.add_argument("--symbol", required=True)
    goblin_validate_artifact.add_argument("--timezone-basis", required=True)
    goblin_validate_artifact.add_argument("--terminal-id", default=None)
    goblin_validate_artifact.add_argument("--terminal-build", default=None)
    goblin_validate_artifact.add_argument("--broker-server", default=None)
    goblin_validate_artifact.add_argument("--artifact-hash", default=None)

    goblin_truth_report = subparsers.add_parser("goblin-build-truth-report", parents=[common])
    goblin_truth_report.add_argument("--candidate-id", required=True)
    goblin_truth_report.add_argument("--governance-effect", default="")
    goblin_truth_report.add_argument("--research-artifact-id", default=None)
    goblin_truth_report.add_argument("--mt5-artifact-id", default=None)
    goblin_truth_report.add_argument("--live-artifact-id", default=None)
    goblin_truth_report.add_argument("--broker-artifact-id", default=None)

    subparsers.add_parser("goblin-show-default-contracts", parents=[common])

    goblin_open_incident = subparsers.add_parser("goblin-open-incident", parents=[common])
    goblin_open_incident.add_argument("--candidate-id", required=True)
    goblin_open_incident.add_argument("--title", required=True)
    goblin_open_incident.add_argument("--incident-id", default=None)
    goblin_open_incident.add_argument("--affected-candidate-id", action="append", dest="affected_candidate_ids")
    goblin_open_incident.add_argument("--blocker", action="append", dest="blockers")
    goblin_open_incident.add_argument("--note", action="append", dest="notes")

    goblin_close_incident = subparsers.add_parser("goblin-close-incident", parents=[common])
    goblin_close_incident.add_argument("--candidate-id", required=True)
    goblin_close_incident.add_argument("--incident-id", required=True)
    goblin_close_incident.add_argument("--resolution-summary", required=True)
    goblin_close_incident.add_argument("--approved-by", default=None)

    goblin_bundle = subparsers.add_parser("goblin-build-deployment-bundle", parents=[common])
    goblin_bundle.add_argument("--candidate-id", required=True)
    goblin_bundle.add_argument("--bundle-id", default=None)
    goblin_bundle.add_argument("--rollback-criterion", action="append", dest="rollback_criteria")

    goblin_investigation_pack = subparsers.add_parser("goblin-build-investigation-pack", parents=[common])
    goblin_investigation_pack.add_argument("--incident-report-path", required=True)
    goblin_investigation_pack.add_argument("--pack-id", default=None)

    goblin_rationale = subparsers.add_parser("goblin-write-rationale-card", parents=[common])
    goblin_rationale.add_argument("--family", required=True)
    goblin_rationale.add_argument("--thesis", required=True)
    goblin_rationale.add_argument("--candidate-id", default=None)
    goblin_rationale.add_argument("--invalidation", action="append", dest="invalidations")
    goblin_rationale.add_argument("--hostile-regime", action="append", dest="hostile_regimes")
    goblin_rationale.add_argument("--execution-assumption", action="append", dest="execution_assumptions")
    goblin_rationale.add_argument("--non-deployable-condition", action="append", dest="non_deployable_conditions")

    goblin_scorecard = subparsers.add_parser("goblin-write-scorecard", parents=[common])
    goblin_scorecard.add_argument("--candidate-id", required=True)
    goblin_scorecard.add_argument("--alpha-quality", type=float, required=True)
    goblin_scorecard.add_argument("--robustness", type=float, required=True)
    goblin_scorecard.add_argument("--executable-parity", type=float, required=True)
    goblin_scorecard.add_argument("--operational-reliability", type=float, required=True)
    goblin_scorecard.add_argument("--deployment-fit", type=float, required=True)
    goblin_scorecard.add_argument("--note", action="append", dest="notes")

    goblin_experiment_ledger = subparsers.add_parser("goblin-write-experiment-ledger", parents=[common])
    goblin_experiment_ledger.add_argument("--family", required=True)
    goblin_experiment_ledger.add_argument("--max-trials-per-family", type=int, default=160)
    goblin_experiment_ledger.add_argument("--max-mutation-depth", type=int, default=8)
    goblin_experiment_ledger.add_argument("--max-failed-refinements", type=int, default=48)

    subparsers.add_parser("goblin-show-approval-boundaries", parents=[common])

    subparsers.add_parser("industry-report", parents=[common])

    live_attach = subparsers.add_parser("goblin-live-attach", parents=[common])
    live_attach.add_argument("--candidate-id", required=True)
    live_attach.add_argument("--run-id", required=True)
    live_attach.add_argument("--terminal-build", required=True)
    live_attach.add_argument("--bundle-id", required=True)
    live_attach.add_argument("--account-id", default="5087443")
    live_attach.add_argument("--chart-symbol", default="EURUSD")
    live_attach.add_argument("--timeframe", default="M1")
    live_attach.add_argument("--leverage", type=float, default=30.0)
    live_attach.add_argument("--lot-mode", default="shadow_only_signal_observation")
    live_attach.add_argument("--broker-server", default="OANDA_UK-Demo-1")
    live_attach.add_argument("--ladder-state", default="shadow_only")

    live_heartbeat = subparsers.add_parser("goblin-live-heartbeat", parents=[common])
    live_heartbeat.add_argument("--candidate-id", required=True)
    live_heartbeat.add_argument("--run-id", required=True)
    live_heartbeat.add_argument("--status", choices=["healthy", "warning", "stale", "offline"], default="healthy")
    live_heartbeat.add_argument("--terminal-active", type=lambda v: v.lower() in ("true", "1", "yes"), default=True)
    live_heartbeat.add_argument(
        "--algo-trading-enabled", type=lambda v: v.lower() in ("true", "1", "yes"), default=True
    )
    live_heartbeat.add_argument("--note", action="append", dest="notes")

    live_session_end = subparsers.add_parser("goblin-live-session-end", parents=[common])
    live_session_end.add_argument("--candidate-id", required=True)
    live_session_end.add_argument("--run-id", required=True)
    live_session_end.add_argument("--mt5-common-path", required=True)
    live_session_end.add_argument("--runtime-summary-path")
    live_session_end.add_argument("--signal-trace-path")
    live_session_end.add_argument("--ea-audit-path")
    live_session_end.add_argument("--broker-csv-path")
    live_session_end.add_argument("--broker-account-id")
    live_session_end.add_argument("--diagnostic-windows-path")
    live_session_end.add_argument("--journal-path")
    live_session_end.add_argument("--experts-log-path")
    live_session_end.add_argument("--note", action="append", dest="notes")

    live_journal = subparsers.add_parser("goblin-live-journal", parents=[common])
    live_journal.add_argument("--candidate-id", required=True)
    live_journal.add_argument("--tail", type=int, default=20, help="Number of lines to tail (default 20)")
    live_journal.add_argument("--mt5-common-path", help="Path to MT5 Common Files (auto-detected if omitted)")

    live_experts = subparsers.add_parser("goblin-live-experts", parents=[common])
    live_experts.add_argument("--candidate-id", required=True)
    live_experts.add_argument("--tail", type=int, default=20, help="Number of lines to tail (default 20)")
    live_experts.add_argument("--mt5-common-path", help="Path to MT5 Common Files (auto-detected if omitted)")

    mt5_cleanup = subparsers.add_parser("goblin-mt5-cleanup", parents=[common])
    mt5_cleanup.add_argument(
        "--keep",
        action="append",
        dest="keep_ids",
        default=[],
        help="Candidate IDs to keep (repeatable). CandidateEA is always kept.",
    )
    mt5_cleanup.add_argument(
        "--dry-run", action="store_true", help="List files that would be removed without deleting them"
    )

    return parser


def _resolve_existing_path(primary: str | None, fallbacks: list[Path]) -> Path | None:
    if primary:
        resolved = Path(primary)
        return resolved if resolved.exists() else None
    for candidate in fallbacks:
        if candidate.exists():
            return candidate
    return None


def _format_missing_note(prefix: str, candidates: list[Path]) -> str:
    return f"{prefix}={'|'.join(str(candidate) for candidate in candidates)}"


def _archive_file(
    source: Path | None, destination: Path, notes: list[str], *, found_note: str, missing_note: str
) -> Path | None:
    if source is None:
        notes.append(missing_note)
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    notes.append(f"{found_note}={source}")
    return destination


def _find_mt5_common_path() -> Path | None:
    """Auto-detect MT5 common files path from standard Windows locations."""
    candidates = [
        Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files",
        Path("C:")
        / "Users"
        / Path.home().name
        / "AppData"
        / "Roaming"
        / "MetaQuotes"
        / "Terminal"
        / "Common"
        / "Files",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _normalize_mt5_common_root(common_base: Path) -> Path:
    if common_base.name.lower() == "files" and common_base.parent.name.lower() == "common":
        return common_base.parent
    return common_base


def _mt5_agentic_forex_roots(common_base: Path) -> list[Path]:
    common_root = _normalize_mt5_common_root(common_base)
    roots: list[Path] = []
    for root in (common_root / "Files" / "AgenticForex", common_root / "AgenticForex"):
        if root not in roots:
            roots.append(root)
    return roots


def _latest_log_file(log_dir: Path) -> Path | None:
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _discover_mt5_terminal_logs(common_base: Path) -> tuple[Path | None, Path | None]:
    """Return newest terminal journal and experts log across detected MT5 terminal hashes."""
    terminals_root = _normalize_mt5_common_root(common_base).parent
    newest_journal: Path | None = None
    newest_experts: Path | None = None

    if not terminals_root.exists():
        return None, None

    for term_dir in terminals_root.iterdir():
        if not (term_dir.is_dir() and len(term_dir.name) == 32):
            continue
        journal_candidate = _latest_log_file(term_dir / "logs")
        experts_candidate = _latest_log_file(term_dir / "MQL5" / "Logs")

        if journal_candidate is not None and (
            newest_journal is None or journal_candidate.stat().st_mtime > newest_journal.stat().st_mtime
        ):
            newest_journal = journal_candidate
        if experts_candidate is not None and (
            newest_experts is None or experts_candidate.stat().st_mtime > newest_experts.stat().st_mtime
        ):
            newest_experts = experts_candidate

    return newest_journal, newest_experts


def _build_live_quality_assessment(
    *,
    settings,
    candidate_id: str,
    run_id: str,
    summary: RuntimeSummary,
    reconciliation_payload: dict[str, object] | None,
) -> dict[str, object]:
    """Create a deterministic candidate-scoped quality assessment for live-demo closeout."""
    forward_report_path = settings.paths().reports_dir / candidate_id / "forward_stage_report.json"
    forward_passed = None
    forward_profit_factor = None
    forward_expectancy_pips = None
    if forward_report_path.exists():
        forward_data = read_json(forward_report_path)
        forward_passed = bool(forward_data.get("passed", False))
        forward_profit_factor = forward_data.get("profit_factor")
        forward_expectancy_pips = forward_data.get("expectancy_pips")

    reconciliation_status = (
        str(reconciliation_payload.get("reconciliation_status", "not_run")) if reconciliation_payload else "not_run"
    )

    order_success_ratio = 1.0 if summary.order_attempts == 0 else summary.order_successes / summary.order_attempts
    quality_score = 100.0
    reasons: list[str] = []

    if summary.order_failures > 0:
        quality_score -= min(40.0, summary.order_failures * 15.0)
        reasons.append(f"order_failures={summary.order_failures}")
    if summary.audit_write_failures > 0:
        quality_score -= min(30.0, summary.audit_write_failures * 10.0)
        reasons.append(f"audit_write_failures={summary.audit_write_failures}")
    if reconciliation_status == "mismatch":
        quality_score -= 35.0
        reasons.append("broker_reconciliation_mismatch")
    elif reconciliation_status == "not_run":
        quality_score -= 10.0
        reasons.append("broker_reconciliation_not_run")
    if forward_passed is False:
        quality_score -= 30.0
        reasons.append("forward_stage_not_passed")
    if summary.signals_generated == 0 and summary.order_attempts == 0:
        quality_score -= 10.0
        reasons.append("insufficient_live_activity")

    quality_score = max(0.0, round(quality_score, 2))

    if quality_score >= 80.0 and summary.audit_write_failures == 0 and reconciliation_status != "mismatch":
        verdict = "healthy"
    elif summary.signals_generated == 0 and summary.order_attempts == 0:
        verdict = "insufficient_evidence"
    else:
        verdict = "risk"

    assessment = {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "verdict": verdict,
        "quality_score": quality_score,
        "order_success_ratio": round(order_success_ratio, 4),
        "strategy_baseline": {
            "forward_stage_report_found": forward_report_path.exists(),
            "forward_stage_passed": forward_passed,
            "forward_profit_factor": forward_profit_factor,
            "forward_expectancy_pips": forward_expectancy_pips,
        },
        "runtime_metrics": {
            "bars_processed": summary.bars_processed,
            "signals_generated": summary.signals_generated,
            "order_attempts": summary.order_attempts,
            "order_successes": summary.order_successes,
            "order_failures": summary.order_failures,
            "spread_blocks": summary.spread_blocks,
            "filter_blocks": summary.filter_blocks,
            "audit_write_failures": summary.audit_write_failures,
        },
        "broker_reconciliation_status": reconciliation_status,
        "reasons": reasons,
    }

    quality_report_path = (
        settings.paths().goblin_live_demo_reports_dir / candidate_id / run_id / "candidate_quality_audit.json"
    )
    quality_report_path.parent.mkdir(parents=True, exist_ok=True)
    quality_report_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    assessment["report_path"] = str(quality_report_path)
    return assessment


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = getattr(args, "project_root", None)
    config_path = getattr(args, "config", None)
    settings = load_settings(project_root=project_root, config_path=config_path)
    tool_registry = build_tool_registry()
    repo = WorkflowRepository(settings.paths())
    llm_client = _build_llm_client(settings)

    if args.command == "catalog-corpus":
        allowed_roots = [Path(args.mirror_path)]
        allowed_roots.extend(
            Path(configured_path).parent
            for configured_path in settings.data.supplemental_source_paths
            if Path(configured_path).exists()
        )
        read_policy = ReadPolicy(project_root=settings.project_root, allowed_external_roots=allowed_roots)
        result = catalog_corpus(Path(args.mirror_path), settings, read_policy)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "ingest-market":
        if args.input_csv:
            result = ingest_market_csv(Path(args.input_csv), settings)
        elif args.oanda_json:
            result = ingest_oanda_json(Path(args.oanda_json), settings)
        elif args.fetch_oanda:
            result = fetch_oanda_candles(
                settings=settings,
                instrument=args.instrument,
                granularity=args.granularity,
                count=args.count,
            )
        elif args.backfill_oanda:
            if not args.start:
                raise ValueError("--start is required when using --backfill-oanda.")
            result = backfill_oanda_history(
                settings=settings,
                start=args.start,
                end=args.end,
                instrument=args.instrument,
                granularity=args.granularity,
                chunk_size=args.chunk_size,
            )
        else:
            result = ingest_mt5_parity_csv(Path(args.mt5_audit_csv), settings)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "qa-market":
        result = assess_market_data_quality(
            settings,
            instrument=args.instrument,
            granularity=args.granularity,
            parquet_path=Path(args.parquet_path) if args.parquet_path else None,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "ingest-calendar":
        result = ingest_economic_calendar(Path(args.input_csv), settings)
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "discover":
        mirror_path = Path(args.mirror_path)
        allowed_roots = [mirror_path]
        allowed_roots.extend(
            Path(configured_path).parent
            for configured_path in settings.data.supplemental_source_paths
            if Path(configured_path).exists()
        )
        read_policy = ReadPolicy(project_root=settings.project_root, allowed_external_roots=allowed_roots)
        if not settings.catalog_path.exists():
            catalog_corpus(mirror_path, settings, read_policy)
        engine = WorkflowEngine(
            settings=settings, llm_client=llm_client, tool_registry=tool_registry, read_policy=read_policy
        )
        workflow = repo.load(args.workflow or settings.workflows.discovery_workflow_id)
        payload = DiscoveryRequest(
            question=args.question,
            family_hint=args.family,
            mirror_path=mirror_path,
        ).model_dump(mode="json")
        trace = engine.run(workflow, payload)
        return _print_trace_result(trace, settings)

    if args.command == "explore-scalping":
        report = explore_scalping_candidates(
            settings,
            mirror_path=Path(args.mirror_path) if args.mirror_path else None,
            max_candidates=args.count,
            max_sources=args.max_sources,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "explore-day-trading":
        report = explore_day_trading_candidates(
            settings,
            mirror_path=Path(args.mirror_path) if args.mirror_path else None,
            max_candidates=args.count,
            max_sources=args.max_sources,
            family_filter=args.family,
            reference_candidate_id=args.reference_candidate,
            max_materialized=args.max_materialized,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "scan-day-trading-behaviors":
        report = scan_day_trading_behaviors(
            settings,
            mirror_path=Path(args.mirror_path) if args.mirror_path else None,
            max_sources=args.max_sources,
            family_filter=args.family,
            reference_candidate_id=args.reference_candidate,
            materialize_candidates=args.refresh_candidates,
            max_materialized=args.max_materialized,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "refine-day-trading-target":
        report = refine_day_trading_target(
            settings,
            target_candidate_id=args.target_id,
            family_override=args.family_override,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "iterate-scalping-target":
        report = iterate_scalping_target(
            settings,
            baseline_candidate_id=args.baseline_id,
            target_candidate_id=args.target_id,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "spec-candidate":
        candidate = CandidateDraft.model_validate(read_json(Path(args.candidate_json)))
        spec = compile_strategy_spec_tool(
            payload=candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
        print(json.dumps(spec, indent=2, default=str))
        return 0

    if args.command == "backtest":
        spec = StrategySpec.model_validate(read_json(Path(args.spec_json)))
        result = run_backtest(spec, settings)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "train-models":
        spec = StrategySpec.model_validate(read_json(Path(args.spec_json)))
        result = train_models(spec, settings)
        print(json.dumps({"report_path": str(result)}, indent=2, default=str))
        return 0

    if args.command == "stress-test":
        spec = StrategySpec.model_validate(read_json(Path(args.spec_json)))
        result = run_stress_test(spec, settings)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "shadow-forward":
        spec = StrategySpec.model_validate(read_json(Path(args.spec_json)))
        result = run_shadow_forward(spec, settings)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "review-candidate":
        spec = StrategySpec.model_validate(read_json(Path(args.spec_json)))
        read_policy = ReadPolicy(project_root=settings.project_root)
        engine = WorkflowEngine(
            settings=settings, llm_client=llm_client, tool_registry=tool_registry, read_policy=read_policy
        )
        workflow = repo.load(args.workflow or settings.workflows.review_workflow_id)
        trace = engine.run(workflow, spec.model_dump(mode="json"))
        return _print_trace_result(trace, settings)

    if args.command == "benchmark-scalping":
        if args.candidate_json:
            candidate = CandidateDraft.model_validate(read_json(Path(args.candidate_json)))
            spec_payload = compile_strategy_spec_tool(
                payload=candidate.model_dump(mode="json"),
                settings=settings,
                config={},
                read_policy=ReadPolicy(project_root=settings.project_root),
            )
            spec = StrategySpec.model_validate(spec_payload)
        else:
            spec = StrategySpec.model_validate(read_json(Path(args.spec_json)))
        report = run_scalping_benchmark(spec, settings)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "compare-experiments":
        report = compare_experiments(
            settings,
            family=args.family,
            candidate_ids=args.candidate_ids,
            limit=args.limit,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-campaign":
        campaign_id = args.campaign_id or f"campaign-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        spec = CampaignSpec(
            campaign_id=campaign_id,
            family=args.family,
            baseline_candidate_id=args.baseline_id,
            target_candidate_ids=args.target_ids,
            max_iterations=args.max_iterations or settings.campaign.max_iterations,
            max_new_candidates=args.max_new_candidates or settings.campaign.max_new_candidates,
            trial_cap_per_family=args.trial_cap or settings.campaign.trial_cap_per_family,
            stop_on_review_eligible_provisional=settings.campaign.stop_on_review_eligible_provisional,
            notes=args.notes or [],
        )
        state = run_bounded_campaign(spec, settings)
        print(json.dumps(state.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-next-step":
        report = run_next_step(
            settings,
            family=args.family,
            parent_campaign_id=args.parent_campaign_id,
            campaign_id=args.campaign_id,
            allowed_step_types=args.allowed_step_types,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-governed-loop":
        report = run_governed_loop(
            settings,
            family=args.family,
            parent_campaign_id=args.parent_campaign_id,
            loop_id=args.loop_id,
            max_steps=args.max_steps,
            allowed_step_types=args.allowed_step_types,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-program-loop":
        report = run_program_loop(
            settings,
            family=args.family,
            parent_campaign_id=args.parent_campaign_id,
            program_id=args.program_id,
            max_lanes=args.max_lanes,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-autonomous-manager":
        report = run_autonomous_manager(
            settings,
            family=args.family,
            parent_campaign_id=args.parent_campaign_id,
            program_id=args.program_id,
            manager_run_id=args.manager_run_id,
            max_cycles=args.max_cycles,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-portfolio-cycle":
        report = run_portfolio_cycle(
            settings,
            slot_id=args.slot,
            run_all_slots=args.all_slots,
            cycle_id=args.cycle_id,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "publish-candidate":
        manifest = publish_candidate(args.candidate_id, settings)
        print(json.dumps(manifest.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "approve":
        record = ApprovalRecord(
            candidate_id=args.candidate_id,
            stage=args.stage,
            decision=args.decision,
            approver=args.approver,
            rationale=args.rationale,
        )
        path = record_approval(record, settings)
        print(json.dumps({"approval_log": str(path), "record": record.model_dump(mode="json")}, indent=2, default=str))
        return 0

    if args.command == "generate-mt5-packet":
        packet = generate_mt5_packet(args.candidate_id, settings)
        print(json.dumps(packet.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "validate-mt5-practice":
        request = MT5ValidationRequest(
            candidate_id=args.candidate_id, audit_csv=Path(args.audit_csv) if args.audit_csv else None
        )
        report = validate_mt5_practice(request.candidate_id, settings, request.audit_csv)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-mt5-manual-test":
        report = run_mt5_manual_test(
            args.candidate_id,
            settings,
            deposit=args.deposit,
            leverage=args.leverage,
            fixed_lots=args.fixed_lots,
            auto_scale_lots=args.auto_scale_lots,
            min_lot=args.min_lot,
            lot_step=args.lot_step,
            tester_mode=args.tester_mode,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-mt5-incident-replay":
        report = run_mt5_incident_replay(
            args.candidate_id,
            settings,
            window_start=args.window_start,
            window_end=args.window_end,
            incident_id=args.incident_id,
            deposit=args.deposit,
            leverage=args.leverage,
            fixed_lots=args.fixed_lots,
            tester_mode=args.tester_mode,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-production-incident":
        report = run_production_incident_analysis(
            settings,
            candidate_id=args.candidate_id,
            incident_id=args.incident_id,
            window_start=args.window_start,
            window_end=args.window_end,
            live_audit_csv=Path(args.live_audit_csv) if args.live_audit_csv else None,
            mt5_replay_audit_csv=Path(args.mt5_replay_audit_csv) if args.mt5_replay_audit_csv else None,
            deterministic_ledger_csv=Path(args.deterministic_ledger_csv) if args.deterministic_ledger_csv else None,
            baseline_tester_report=Path(args.baseline_tester_report) if args.baseline_tester_report else None,
            same_window_tester_report=Path(args.same_window_tester_report) if args.same_window_tester_report else None,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "audit-parity-scope":
        report = build_parity_scope_audit(settings, write_docs=not args.no_write_docs)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "sync-codex-capabilities":
        report = sync_codex_capabilities(settings, run_id=args.run_id)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "export-operator-state":
        report = export_operator_state(settings, run_id=args.run_id, family=args.family)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "validate-operator-contract":
        report = validate_operator_contract(settings)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        if args.strict and not report.passed:
            return 1
        return 0

    if args.command == "audit-candidate-branches":
        report = audit_candidate_branches(
            settings,
            candidate_ids=args.candidate_ids,
            next_family_hint=args.next_family_hint,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "audit-candidate-window-density":
        report = audit_candidate_window_density(
            settings,
            candidate_ids=args.candidate_ids,
            reference_candidate_id=args.reference_candidate,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "queue-snapshot":
        report = build_queue_snapshot(settings, family=args.family)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "run-governed-action":
        manifest = run_governed_action(
            settings,
            action=args.action,
            run_id=args.run_id,
            family=args.family,
            parent_campaign_id=args.parent_campaign_id,
            campaign_id=args.campaign_id,
            allowed_step_types=args.allowed_step_types,
            loop_id=args.loop_id,
            max_steps=args.max_steps,
            program_id=args.program_id,
            max_lanes=args.max_lanes,
            manager_run_id=args.manager_run_id,
            max_cycles=args.max_cycles,
            cycle_id=args.cycle_id,
            slot_id=args.slot,
            all_slots=args.all_slots,
        )
        print(json.dumps(manifest.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "inspect-governed-action":
        report = inspect_governed_action(
            settings,
            run_id=args.run_id,
            manifest_path=Path(args.manifest_path) if args.manifest_path else None,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "setup-oanda-credential":
        result = _setup_oanda_credential(
            settings,
            target=args.target,
            username=args.username,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "goblin-init":
        report = initialize_goblin_program(settings, refresh_docs=args.refresh_docs)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-status":
        report = get_goblin_program_status(settings)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-startup":
        print(_render_goblin_startup(settings, focus=args.focus))
        return 0

    if args.command == "goblin-phase-update":
        phase_record = update_goblin_phase(
            settings,
            phase_id=args.phase_id,
            status=args.status,
            note=(args.notes or [None])[0],
            owner=args.owner,
            acceptance_updates=_parse_acceptance_updates(args.acceptance_updates),
        )
        for blocker in args.blockers or []:
            phase_record = update_goblin_phase(settings, phase_id=args.phase_id, blocker=blocker)
        for note in (args.notes or [])[1:]:
            phase_record = update_goblin_phase(settings, phase_id=args.phase_id, note=note)
        print(json.dumps(phase_record.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-checkpoint":
        report = create_goblin_checkpoint(
            settings,
            phase_id=args.phase_id,
            checkpoint_id=args.checkpoint_id,
            summary=args.summary,
            authoritative_artifacts=args.authoritative_artifacts,
            regenerable_artifacts=args.regenerable_artifacts,
            status=args.status,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-register-artifact":
        provenance = _goblin_provenance_from_args(args)
        record = register_artifact(
            settings,
            provenance=provenance,
            artifact_path=Path(args.artifact_path),
            authoritative=args.authoritative,
            snapshot=not args.no_snapshot,
        )
        print(json.dumps(record.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-validate-artifact":
        provenance = _goblin_provenance_from_args(args)
        report = validate_artifact_provenance(
            settings,
            provenance=provenance,
            artifact_path=Path(args.artifact_path),
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0 if report.valid else 1

    if args.command == "goblin-build-truth-report":
        artifact_records = {
            "research_backtest": artifact_by_id(
                settings, channel="research_backtest", artifact_id=args.research_artifact_id
            )
            if args.research_artifact_id
            else latest_registered_artifact(settings, channel="research_backtest", candidate_id=args.candidate_id),
            "mt5_replay": artifact_by_id(settings, channel="mt5_replay", artifact_id=args.mt5_artifact_id)
            if args.mt5_artifact_id
            else latest_registered_artifact(settings, channel="mt5_replay", candidate_id=args.candidate_id),
            "live_demo": artifact_by_id(settings, channel="live_demo", artifact_id=args.live_artifact_id)
            if args.live_artifact_id
            else latest_registered_artifact(settings, channel="live_demo", candidate_id=args.candidate_id),
            "broker_account_history": artifact_by_id(
                settings, channel="broker_account_history", artifact_id=args.broker_artifact_id
            )
            if args.broker_artifact_id
            else latest_registered_artifact(settings, channel="broker_account_history", candidate_id=args.candidate_id),
        }
        report = build_truth_alignment_report(
            settings,
            candidate_id=args.candidate_id,
            artifact_records=artifact_records,  # type: ignore[arg-type]
            governance_effect=args.governance_effect,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-show-default-contracts":
        payload = {
            "research_data_contract": build_default_research_data_contract(settings).model_dump(mode="json"),
            "time_session_contract": build_default_time_session_contract(settings).model_dump(mode="json"),
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0

    if args.command == "goblin-open-incident":
        report = open_incident_record(
            settings,
            candidate_id=args.candidate_id,
            title=args.title,
            incident_id=args.incident_id,
            affected_candidate_ids=args.affected_candidate_ids,
            blockers=args.blockers,
            notes=args.notes,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-close-incident":
        report = close_incident_record(
            settings,
            candidate_id=args.candidate_id,
            incident_id=args.incident_id,
            resolution_summary=args.resolution_summary,
            approved_by=args.approved_by,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-build-deployment-bundle":
        report = build_deployment_bundle(
            settings,
            candidate_id=args.candidate_id,
            bundle_id=args.bundle_id,
            rollback_criteria=args.rollback_criteria,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-build-investigation-pack":
        report = build_incident_investigation_pack(
            settings,
            incident_report_path=Path(args.incident_report_path),
            pack_id=args.pack_id,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-write-rationale-card":
        report = write_strategy_rationale_card(
            settings,
            family=args.family,
            thesis=args.thesis,
            candidate_id=args.candidate_id,
            invalidation_conditions=args.invalidations,
            hostile_regimes=args.hostile_regimes,
            execution_assumptions=args.execution_assumptions,
            non_deployable_conditions=args.non_deployable_conditions,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-write-scorecard":
        report = write_candidate_scorecard(
            settings,
            candidate_id=args.candidate_id,
            alpha_quality=args.alpha_quality,
            robustness=args.robustness,
            executable_parity=args.executable_parity,
            operational_reliability=args.operational_reliability,
            deployment_fit=args.deployment_fit,
            notes=args.notes,
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-write-experiment-ledger":
        report = write_experiment_accounting_ledger(
            settings,
            family=args.family,
            budget_caps={
                "max_trials_per_family": args.max_trials_per_family,
                "max_mutation_depth": args.max_mutation_depth,
                "max_failed_refinements": args.max_failed_refinements,
            },
        )
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-show-approval-boundaries":
        report = default_approval_boundaries(settings)
        print(json.dumps([item.model_dump(mode="json") for item in report], indent=2, default=str))
        return 0

    if args.command == "industry-report":
        report = generate_industry_report(settings)
        print(json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-live-attach":
        bundle_dir = settings.paths().goblin_deployment_bundles_dir / args.candidate_id
        bundle_path = bundle_dir / f"{args.bundle_id}.json"
        if not bundle_path.exists():
            print(f"ERROR: Bundle not found: {bundle_path}", flush=True)
            return 1

        # --- Auto deploy + compile + hash update ---
        print(f"Deploying {args.candidate_id} to MT5...", flush=True)
        try:
            deploy_result = deploy_and_compile_candidate_ea(
                settings,
                candidate_id=args.candidate_id,
                target_filename=f"{args.candidate_id}.mq5",
            )
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"ERROR: Deploy/compile failed: {exc}", flush=True)
            return 1
        print(f"  Compiled: {deploy_result.compiled_ex5_path}", flush=True)
        print(f"  Source hash:  {deploy_result.source_hash}", flush=True)
        print(f"  Build hash:   {deploy_result.build_hash}", flush=True)

        bundle_data = read_json(bundle_path)
        bundle_data["ea_build_hash"] = deploy_result.build_hash
        bundle_data["inputs_hash"] = deploy_result.source_hash
        bundle_path.write_text(json.dumps(bundle_data, indent=2), encoding="utf-8")
        print(f"  Bundle hashes updated: {bundle_path.name}", flush=True)

        bundle = DeploymentBundle.model_validate(read_json(bundle_path))
        manifest = LiveAttachManifest(
            candidate_id=args.candidate_id,
            run_id=args.run_id,
            account_id=args.account_id,
            chart_symbol=args.chart_symbol,
            timeframe=args.timeframe,
            leverage=args.leverage,
            lot_mode=args.lot_mode,
            terminal_build=args.terminal_build,
            broker_server=args.broker_server,
            attachment_confirmed=True,
            inputs_hash=bundle.inputs_hash,
            bundle_id=args.bundle_id,
            ladder_state=args.ladder_state,
        )
        violations = validate_attach_against_bundle(settings, manifest=manifest, bundle=bundle)
        if violations:
            print("ERROR: Attach blocked by bundle validation:", flush=True)
            for v in violations:
                print(f"  - {v}", flush=True)
            return 1
        result = write_live_attach_manifest(settings, manifest=manifest)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        print(
            f"\nNext: Attach CandidateEA to {args.chart_symbol} {args.timeframe} in MT5, enable Algo Trading.",
            flush=True,
        )
        return 0

    if args.command == "goblin-live-heartbeat":
        heartbeat = RuntimeHeartbeat(
            candidate_id=args.candidate_id,
            run_id=args.run_id,
            status=args.status,
            terminal_active=args.terminal_active,
            algo_trading_enabled=args.algo_trading_enabled,
            notes=args.notes or [],
        )
        result = write_runtime_heartbeat(settings, heartbeat=heartbeat)
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.command == "goblin-live-session-end":
        common_base = Path(args.mt5_common_path) if args.mt5_common_path else _find_mt5_common_path()
        if common_base is None:
            print("ERROR: MT5 common files path not found. Specify --mt5-common-path.", file=sys.stderr)
            return 1
        agentic_forex_roots = _mt5_agentic_forex_roots(common_base)
        live_demo_bases = [root / "LiveDemo" / args.candidate_id for root in agentic_forex_roots]
        audit_bases = [root / "Audit" for root in agentic_forex_roots]
        report_dir = settings.paths().goblin_live_demo_reports_dir / args.candidate_id / args.run_id
        broker_report_dir = settings.paths().goblin_broker_history_reports_dir / args.candidate_id / args.run_id
        runtime_summary_candidates = [base / "runtime_summary.json" for base in live_demo_bases]
        ea_runtime_path = _resolve_existing_path(
            args.runtime_summary_path,
            runtime_summary_candidates,
        )
        signal_trace_candidates = [base / "signal_trace.csv" for base in live_demo_bases]
        ea_signal_trace_path = _resolve_existing_path(
            args.signal_trace_path,
            signal_trace_candidates,
        )
        ea_audit_candidates = [base / "ea_audit.json" for base in live_demo_bases]
        ea_audit_candidates.extend(base / "ea_audit.csv" for base in live_demo_bases)
        for audit_base in audit_bases:
            ea_audit_candidates.extend(
                [
                    audit_base / f"{args.candidate_id}__{args.run_id}__audit.csv",
                    audit_base / f"{args.candidate_id}__audit.csv",
                ]
            )
        ea_audit_path = _resolve_existing_path(
            args.ea_audit_path,
            ea_audit_candidates,
        )
        broker_csv_candidates: list[Path] = []
        for audit_base in audit_bases:
            broker_csv_candidates.extend(
                [
                    audit_base / f"{args.candidate_id}__{args.run_id}__broker_history.csv",
                    audit_base / f"{args.candidate_id}__broker_history.csv",
                ]
            )
        broker_csv_path = _resolve_existing_path(
            args.broker_csv_path,
            broker_csv_candidates,
        )
        diagnostic_window_candidates: list[Path] = []
        for audit_base in audit_bases:
            diagnostic_window_candidates.extend(
                [
                    audit_base / f"{args.candidate_id}__{args.run_id}__diagnostic_tick_windows.csv",
                    audit_base / f"{args.candidate_id}__diagnostic_tick_windows.csv",
                ]
            )
        diagnostic_windows_path = _resolve_existing_path(
            args.diagnostic_windows_path,
            diagnostic_window_candidates,
        )
        journal_path = _resolve_existing_path(args.journal_path, [])
        experts_log_path = _resolve_existing_path(args.experts_log_path, [])
        auto_journal_path, auto_experts_path = _discover_mt5_terminal_logs(common_base)
        if journal_path is None:
            journal_path = auto_journal_path
        if experts_log_path is None:
            experts_log_path = auto_experts_path
        notes = list(args.notes or [])
        bars_processed = 0
        allowed_hour_bars = 0
        signals_generated = 0
        order_attempts = 0
        order_successes = 0
        order_failures = 0
        spread_blocks = 0
        filter_blocks = 0
        audit_write_failures = 0
        if ea_runtime_path is not None and ea_runtime_path.exists():
            ea_data = read_json(ea_runtime_path)
            bars_processed = int(ea_data.get("bars_processed", 0))
            allowed_hour_bars = int(ea_data.get("allowed_hour_bars", 0))
            signals_generated = int(ea_data.get("long_signals", 0)) + int(ea_data.get("short_signals", 0))
            order_attempts = int(ea_data.get("order_attempts", 0))
            order_successes = int(ea_data.get("order_successes", 0))
            order_failures = int(ea_data.get("order_failures", 0))
            spread_blocks = int(ea_data.get("spread_blocked_bars", 0))
            filter_blocks = int(ea_data.get("filter_blocked_bars", 0))
            audit_write_failures = int(ea_data.get("audit_write_failures", 0))
            notes.append(f"ea_runtime_summary_source={ea_runtime_path}")
        else:
            notes.append(_format_missing_note("ea_runtime_summary_not_found", runtime_summary_candidates))

        report_dir.mkdir(parents=True, exist_ok=True)
        archived_signal_trace = _archive_file(
            ea_signal_trace_path,
            report_dir / "signal_trace.csv",
            notes,
            found_note="signal_trace_copied",
            missing_note=_format_missing_note("signal_trace_not_found", signal_trace_candidates),
        )
        ea_audit_destination = report_dir / (
            f"ea_audit{ea_audit_path.suffix.lower()}" if ea_audit_path is not None and ea_audit_path.suffix else "ea_audit.json"
        )
        archived_ea_audit = _archive_file(
            ea_audit_path,
            ea_audit_destination,
            notes,
            found_note="ea_audit_copied",
            missing_note=_format_missing_note("ea_audit_not_found", ea_audit_candidates),
        )
        _archive_file(
            diagnostic_windows_path,
            report_dir / "diagnostic_tick_windows.csv",
            notes,
            found_note="diagnostic_windows_copied",
            missing_note=_format_missing_note("diagnostic_windows_not_found", diagnostic_window_candidates),
        )
        _archive_file(
            journal_path,
            report_dir / "terminal_journal.log",
            notes,
            found_note="terminal_journal_copied",
            missing_note="terminal_journal_not_found",
        )
        _archive_file(
            experts_log_path,
            report_dir / "experts.log",
            notes,
            found_note="experts_log_copied",
            missing_note="experts_log_not_found",
        )

        archived_broker_csv = _archive_file(
            broker_csv_path,
            broker_report_dir / "broker_history.csv",
            notes,
            found_note="broker_history_copied",
            missing_note=_format_missing_note("broker_history_not_found", broker_csv_candidates),
        )

        reconciliation_payload = None
        if archived_broker_csv is not None:
            reconciliation = run_broker_reconciliation(
                settings,
                candidate_id=args.candidate_id,
                run_id=args.run_id,
                broker_csv_path=archived_broker_csv,
                account_id=args.broker_account_id,
                ea_audit_path=archived_ea_audit,
            )
            notes.append(f"broker_reconciliation_status={reconciliation.reconciliation_status}")
            reconciliation_payload = reconciliation.model_dump(mode="json")
        else:
            notes.append("broker_reconciliation_skipped=no_broker_history")

        summary = RuntimeSummary(
            candidate_id=args.candidate_id,
            run_id=args.run_id,
            bars_processed=bars_processed,
            allowed_hour_bars=allowed_hour_bars,
            signals_generated=signals_generated,
            order_attempts=order_attempts,
            order_successes=order_successes,
            order_failures=order_failures,
            spread_blocks=spread_blocks,
            filter_blocks=filter_blocks,
            audit_write_failures=audit_write_failures,
            notes=notes,
        )
        result = write_runtime_summary(settings, summary=summary)
        quality_assessment = _build_live_quality_assessment(
            settings=settings,
            candidate_id=args.candidate_id,
            run_id=args.run_id,
            summary=result,
            reconciliation_payload=reconciliation_payload,
        )
        print(
            json.dumps(
                {
                    "runtime_summary": result.model_dump(mode="json"),
                    "archived_signal_trace": str(archived_signal_trace) if archived_signal_trace else None,
                    "archived_ea_audit": str(archived_ea_audit) if archived_ea_audit else None,
                    "archived_broker_history": str(archived_broker_csv) if archived_broker_csv else None,
                    "broker_reconciliation": reconciliation_payload,
                    "quality_assessment": quality_assessment,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    if args.command == "goblin-live-journal":
        """Tail the active MT5 terminal journal for a candidate."""
        common_base = Path(args.mt5_common_path) if args.mt5_common_path else _find_mt5_common_path()
        if not common_base:
            print("ERROR: MT5 common files path not found. Specify --mt5-common-path.", file=sys.stderr)
            return 1

        journal_path, _ = _discover_mt5_terminal_logs(common_base)
        if journal_path is None:
            print(
                f"ERROR: No active MT5 terminal journal found. Ensure MT5 is running with {args.candidate_id} EA.",
                file=sys.stderr,
            )
            return 1

        try:
            with open(journal_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                tail_lines = lines[-args.tail :] if args.tail > 0 else lines
                print(f"# Journal: {journal_path.name} (tail -{args.tail})")
                print(f"# Updated: {datetime.fromtimestamp(journal_path.stat().st_mtime, tz=UTC).isoformat()}")
                print()
                print("".join(tail_lines), end="")
        except Exception as e:
            print(f"ERROR reading journal: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "goblin-live-experts":
        """Tail the active MT5 experts log for a candidate."""
        common_base = Path(args.mt5_common_path) if args.mt5_common_path else _find_mt5_common_path()
        if not common_base:
            print("ERROR: MT5 common files path not found. Specify --mt5-common-path.", file=sys.stderr)
            return 1

        _, experts_path = _discover_mt5_terminal_logs(common_base)
        if experts_path is None:
            print(
                f"ERROR: No active MT5 experts log found. Ensure MT5 is running with {args.candidate_id} EA.",
                file=sys.stderr,
            )
            return 1

        try:
            with open(experts_path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                tail_lines = lines[-args.tail :] if args.tail > 0 else lines
                print(f"# Experts Log: {experts_path.name} (tail -{args.tail})")
                print(f"# Updated: {datetime.fromtimestamp(experts_path.stat().st_mtime, tz=UTC).isoformat()}")
                print()
                print("".join(tail_lines), end="")
        except Exception as e:
            print(f"ERROR reading experts log: {e}", file=sys.stderr)
            return 1
        return 0

    if args.command == "goblin-mt5-cleanup":
        result = cleanup_mt5_experts(
            settings,
            keep_ids=args.keep_ids,
            dry_run=args.dry_run,
        )
        prefix = "[DRY RUN] " if args.dry_run else ""
        print(f"{prefix}Experts dir: {result.experts_dir}")
        print(f"{prefix}Kept ({len(result.kept)}): {', '.join(result.kept) if result.kept else '(none)'}")
        print(f"{prefix}Removed ({len(result.removed)}): {', '.join(result.removed) if result.removed else '(none)'}")
        return 0

    return 1


_GOBLIN_STARTUP_BANNER = """\
    _____       _     _ _
  / ____|     | |   | (_)
 | |  __  ___ | |__ | |_ _ __
 | | |_ |/ _ \\| '_ \\| | | '_ \\
 | |__| | (_) | |_) | | | | | |
  \\_____|\\___/|_.__/|_|_|_| |_|
"""


def _render_goblin_startup(settings, *, focus: str | None = None) -> str:
    status_path = settings.paths().root / "Goblin" / "STATUS.md"
    current_phase = _extract_markdown_field(status_path, "Current phase")
    if not current_phase or current_phase == "none":
        current_phase = "S1+ ready (post-takeover multi-timezone strategy program)"
    completed_phase_count = _count_completed_phase_files(settings.paths().goblin_phase_state_dir)
    remaining_phase_ids = _extract_s1_phase_ids(settings.paths().root / "Goblin" / "S1_PLUS_PLAN.md")
    recommendation = _goblin_startup_recommendation(focus=focus)

    lines = [
        _GOBLIN_STARTUP_BANNER.rstrip(),
        "",
        "Goblin startup",
        f"Status: {current_phase or 'unknown'}",
        f"Tracked Goblin platform phases complete: {completed_phase_count}",
        "",
        "Remaining plan:",
    ]
    lines.extend(f"- {phase_id}" for phase_id in remaining_phase_ids)
    lines.extend(["", "Recommended next:", recommendation])
    if focus:
        lines.extend(["", f"Focus: {focus}"])
    return "\n".join(lines)


def _extract_markdown_field(path: Path, field_name: str) -> str | None:
    if not path.exists():
        return None
    prefix = f"- {field_name}: `"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix) and line.endswith("`"):
            return line[len(prefix) : -1]
    return None


def _extract_s1_phase_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    phase_ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("| `S1-P"):
            phase_ids.append(stripped.split("`")[1])
    return phase_ids


def _extract_status_count(path: Path, label: str) -> int:
    if not path.exists():
        return 0
    prefix = f"- `{label}`: "
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            raw_value = stripped[len(prefix) :]
            try:
                return int(raw_value)
            except ValueError:
                return 0
    return 0


def _count_completed_phase_files(phase_dir: Path) -> int:
    if not phase_dir.exists():
        return 0
    completed = 0
    for path in phase_dir.glob("GOBLIN-*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("status") == "completed":
            completed += 1
    return completed


def _goblin_startup_recommendation(*, focus: str | None = None) -> str:
    normalized_focus = (focus or "").strip().lower()
    if normalized_focus in {"af-cand-0733", "bundle a", "s1-p01", "s1-p02"}:
        return textwrap.dedent(
            """\
            Start Bundle A: formalize AF-CAND-0733 as the S1-P01 stage card,
            freeze the candidate, bundle, and session scope in artifacts, and
            stop only after the first governed shadow_only activation checkpoint.
            """
        ).strip()
    return textwrap.dedent(
        """\
        Start S1-P01: create the first candidate stage card and lane declaration,
        then work only through Bundle A until the first candidate is activated as
        a governed shadow_only live-demo object.
        """
    ).strip()


def _build_llm_client(settings):
    if settings.llm.provider in {"openai", "openai_legacy"}:
        return OpenAIClient(settings)
    return MockLLMClient()


def _goblin_provenance_from_args(args) -> ArtifactProvenance:
    return ArtifactProvenance(
        candidate_id=args.candidate_id,
        run_id=args.run_id,
        artifact_origin=args.artifact_origin,
        evidence_channel=args.channel,
        terminal_id=args.terminal_id,
        terminal_build=args.terminal_build,
        broker_server=args.broker_server,
        symbol=args.symbol,
        timezone_basis=args.timezone_basis,
        artifact_hash=args.artifact_hash,
    )


def _parse_acceptance_updates(values: list[str] | None) -> dict[str, object] | None:
    if not values:
        return None
    parsed: dict[str, object] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid acceptance update, expected key=value: {item}")
        key, raw_value = item.split("=", 1)
        normalized = raw_value.strip()
        if normalized.lower() in {"true", "false"}:
            parsed[key] = normalized.lower() == "true"
            continue
        try:
            parsed[key] = int(normalized)
            continue
        except ValueError:
            pass
        try:
            parsed[key] = float(normalized)
            continue
        except ValueError:
            pass
        parsed[key] = normalized
    return parsed


def _print_trace_result(trace, settings) -> int:
    if trace.output_payload is None or any(item.error for item in trace.node_traces):
        failed_node = next((item for item in trace.node_traces if item.error), None)
        print(
            json.dumps(
                {
                    "trace_id": trace.trace_id,
                    "trace_path": str(settings.paths().traces_dir / trace.trace_id / "trace.json"),
                    "error": failed_node.error if failed_node else "Workflow completed without an output payload.",
                    "failed_node": failed_node.node_id if failed_node else None,
                },
                indent=2,
                default=str,
            )
        )
        return 1
    print(json.dumps(trace.output_payload, indent=2, default=str))
    return 0


def _setup_oanda_credential(
    settings,
    *,
    target: str | None = None,
    username: str = "api-token",
    prompt_secret=getpass.getpass,
    writer=write_windows_credential,
) -> dict:
    resolved_target = target or settings.oanda.credential_targets[0]
    token = prompt_secret("Enter OANDA practice API token: ").strip()
    if not token:
        raise ValueError("OANDA API token entry was empty.")
    confirmation = prompt_secret("Confirm OANDA practice API token: ").strip()
    if token != confirmation:
        raise ValueError("OANDA API token confirmation did not match.")
    writer(
        resolved_target,
        token,
        username=username,
        comment="Agentic Forex OANDA practice token",
    )
    return {
        "stored": True,
        "target": resolved_target,
        "username": username,
        "message": "OANDA token stored in Windows Credential Manager.",
    }
