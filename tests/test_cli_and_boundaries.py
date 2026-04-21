from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import TEMPLATE_ROOT, create_corpus_mirror, create_oanda_candles_json

from agentic_forex.cli.app import build_parser
from agentic_forex.runtime.security import ProjectIsolationError, ReadPolicy


def test_parser_preserves_root_level_common_args():
    parser = build_parser()

    before = parser.parse_args(
        [
            "--project-root",
            "C:\\agentic-forex",
            "--config",
            "C:\\agentic-forex\\config\\openai-live.toml",
            "discover",
            "--question",
            "Build a scalping strategy for EUR/USD",
            "--mirror-path",
            "C:\\gnidart",
        ]
    )
    after = parser.parse_args(
        [
            "discover",
            "--project-root",
            "C:\\agentic-forex",
            "--config",
            "C:\\agentic-forex\\config\\openai-live.toml",
            "--question",
            "Build a scalping strategy for EUR/USD",
            "--mirror-path",
            "C:\\gnidart",
        ]
    )

    assert before.project_root == "C:\\agentic-forex"
    assert before.config == "C:\\agentic-forex\\config\\openai-live.toml"
    assert after.project_root == "C:\\agentic-forex"
    assert after.config == "C:\\agentic-forex\\config\\openai-live.toml"


def test_parser_supports_audit_parity_scope_command():
    parser = build_parser()

    args = parser.parse_args(
        [
            "audit-parity-scope",
            "--project-root",
            "C:\\agentic-forex",
            "--no-write-docs",
        ]
    )

    assert args.command == "audit-parity-scope"
    assert args.project_root == "C:\\agentic-forex"
    assert args.no_write_docs is True


def test_parser_supports_run_mt5_manual_test_command():
    parser = build_parser()

    args = parser.parse_args(
        [
            "run-mt5-manual-test",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0263",
            "--deposit",
            "100",
            "--leverage",
            "33",
            "--auto-scale-lots",
        ]
    )

    assert args.command == "run-mt5-manual-test"
    assert args.project_root == "C:\\agentic-forex"
    assert args.candidate_id == "AF-CAND-0263"
    assert args.deposit == 100.0
    assert args.leverage == 33.0
    assert args.auto_scale_lots is True


def test_parser_supports_incident_commands():
    parser = build_parser()

    replay_args = parser.parse_args(
        [
            "run-mt5-incident-replay",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0263",
            "--window-start",
            "2026-03-25",
            "--window-end",
            "2026-04-11",
            "--fixed-lots",
            "0.01",
        ]
    )
    incident_args = parser.parse_args(
        [
            "run-production-incident",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0263",
            "--live-audit-csv",
            "C:\\tmp\\live.csv",
        ]
    )

    assert replay_args.command == "run-mt5-incident-replay"
    assert replay_args.window_start == "2026-03-25"
    assert replay_args.fixed_lots == 0.01
    assert incident_args.command == "run-production-incident"
    assert incident_args.live_audit_csv == "C:\\tmp\\live.csv"


def test_parser_supports_run_portfolio_cycle_command():
    parser = build_parser()

    args = parser.parse_args(
        [
            "run-portfolio-cycle",
            "--project-root",
            "C:\\agentic-forex",
            "--slot",
            "slot_b",
        ]
    )

    assert args.command == "run-portfolio-cycle"
    assert args.project_root == "C:\\agentic-forex"
    assert args.slot == "slot_b"
    assert args.all_slots is False


def test_parser_supports_codex_operator_commands():
    parser = build_parser()

    sync_args = parser.parse_args(
        [
            "sync-codex-capabilities",
            "--project-root",
            "C:\\agentic-forex",
            "--run-id",
            "cap-sync-001",
        ]
    )
    governed_args = parser.parse_args(
        [
            "run-governed-action",
            "--project-root",
            "C:\\agentic-forex",
            "--action",
            "program_loop",
            "--family",
            "scalping",
            "--run-id",
            "governed-001",
        ]
    )
    inspect_args = parser.parse_args(
        [
            "inspect-governed-action",
            "--project-root",
            "C:\\agentic-forex",
            "--run-id",
            "governed-001",
        ]
    )
    audit_args = parser.parse_args(
        [
            "audit-candidate-branches",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0291",
            "--candidate-id",
            "AF-CAND-0328",
            "--next-family-hint",
            "europe_open_compression_reversion_research",
        ]
    )
    audit_window_args = parser.parse_args(
        [
            "audit-candidate-window-density",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0414",
            "--candidate-id",
            "AF-CAND-0416",
            "--reference-candidate",
            "AF-CAND-0414",
        ]
    )

    assert sync_args.command == "sync-codex-capabilities"
    assert sync_args.run_id == "cap-sync-001"
    assert governed_args.command == "run-governed-action"
    assert governed_args.action == "program_loop"
    assert governed_args.run_id == "governed-001"
    assert inspect_args.command == "inspect-governed-action"
    assert inspect_args.run_id == "governed-001"
    assert audit_args.command == "audit-candidate-branches"
    assert audit_args.candidate_ids == ["AF-CAND-0291", "AF-CAND-0328"]
    assert audit_args.next_family_hint == "europe_open_compression_reversion_research"
    assert audit_window_args.command == "audit-candidate-window-density"
    assert audit_window_args.candidate_ids == ["AF-CAND-0414", "AF-CAND-0416"]
    assert audit_window_args.reference_candidate == "AF-CAND-0414"


def test_parser_supports_goblin_commands():
    parser = build_parser()

    init_args = parser.parse_args(
        [
            "goblin-init",
            "--project-root",
            "C:\\agentic-forex",
            "--refresh-docs",
        ]
    )
    status_args = parser.parse_args(
        [
            "goblin-status",
            "--project-root",
            "C:\\agentic-forex",
        ]
    )
    startup_args = parser.parse_args(
        [
            "goblin-startup",
            "--project-root",
            "C:\\agentic-forex",
            "--focus",
            "AF-CAND-0733",
        ]
    )
    phase_args = parser.parse_args(
        [
            "goblin-phase-update",
            "--project-root",
            "C:\\agentic-forex",
            "--phase-id",
            "GOBLIN-P00",
            "--status",
            "completed",
            "--note",
            "foundation implemented",
            "--acceptance",
            "tests_passed=17",
        ]
    )
    checkpoint_args = parser.parse_args(
        [
            "goblin-checkpoint",
            "--project-root",
            "C:\\agentic-forex",
            "--phase-id",
            "GOBLIN-P00",
            "--summary",
            "Initialized Goblin",
            "--authoritative-artifact",
            "Goblin/PROGRAM.md",
        ]
    )
    register_args = parser.parse_args(
        [
            "goblin-register-artifact",
            "--project-root",
            "C:\\agentic-forex",
            "--channel",
            "research_backtest",
            "--candidate-id",
            "AF-CAND-0263",
            "--run-id",
            "run-001",
            "--artifact-origin",
            "backtest_summary",
            "--artifact-path",
            "C:\\tmp\\artifact.json",
            "--symbol",
            "EUR_USD",
            "--timezone-basis",
            "UTC",
        ]
    )
    truth_args = parser.parse_args(
        [
            "goblin-build-truth-report",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0263",
        ]
    )
    default_contract_args = parser.parse_args(
        [
            "goblin-show-default-contracts",
            "--project-root",
            "C:\\agentic-forex",
        ]
    )
    incident_args = parser.parse_args(
        [
            "goblin-open-incident",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0263",
            "--title",
            "Parity mismatch",
        ]
    )
    bundle_args = parser.parse_args(
        [
            "goblin-build-deployment-bundle",
            "--project-root",
            "C:\\agentic-forex",
            "--candidate-id",
            "AF-CAND-0263",
        ]
    )
    investigation_args = parser.parse_args(
        [
            "goblin-build-investigation-pack",
            "--project-root",
            "C:\\agentic-forex",
            "--incident-report-path",
            "C:\\agentic-forex\\data\\state\\incidents\\AF-CAND-0263\\incident_report.json",
        ]
    )
    rationale_args = parser.parse_args(
        [
            "goblin-write-rationale-card",
            "--project-root",
            "C:\\agentic-forex",
            "--family",
            "overlap_resolution_bridge_research",
            "--thesis",
            "Session dislocation mean reversion",
        ]
    )
    boundaries_args = parser.parse_args(
        [
            "goblin-show-approval-boundaries",
            "--project-root",
            "C:\\agentic-forex",
        ]
    )

    assert init_args.command == "goblin-init"
    assert init_args.refresh_docs is True
    assert status_args.command == "goblin-status"
    assert startup_args.command == "goblin-startup"
    assert startup_args.focus == "AF-CAND-0733"
    assert phase_args.command == "goblin-phase-update"
    assert phase_args.phase_id == "GOBLIN-P00"
    assert phase_args.acceptance_updates == ["tests_passed=17"]
    assert checkpoint_args.command == "goblin-checkpoint"
    assert checkpoint_args.authoritative_artifacts == ["Goblin/PROGRAM.md"]
    assert register_args.command == "goblin-register-artifact"
    assert register_args.channel == "research_backtest"
    assert truth_args.command == "goblin-build-truth-report"
    assert default_contract_args.command == "goblin-show-default-contracts"
    assert incident_args.command == "goblin-open-incident"
    assert bundle_args.command == "goblin-build-deployment-bundle"
    assert investigation_args.command == "goblin-build-investigation-pack"
    assert rationale_args.command == "goblin-write-rationale-card"
    assert boundaries_args.command == "goblin-show-approval-boundaries"


def test_parser_supports_refine_day_trading_target_command():
    parser = build_parser()

    args = parser.parse_args(
        [
            "refine-day-trading-target",
            "--project-root",
            "C:\\agentic-forex",
            "--target-id",
            "AF-CAND-0278",
            "--family-override",
            "europe_open_compression_research",
        ]
    )

    assert args.command == "refine-day-trading-target"
    assert args.target_id == "AF-CAND-0278"
    assert args.family_override == "europe_open_compression_research"


def test_parser_supports_targeted_day_trading_exploration_family():
    parser = build_parser()

    args = parser.parse_args(
        [
            "explore-day-trading",
            "--project-root",
            "C:\\agentic-forex",
            "--family",
            "asia_europe_transition_daytype_reclaim_research",
            "--count",
            "2",
            "--reference-candidate",
            "AF-CAND-0414",
            "--max-materialized",
            "3",
        ]
    )

    assert args.command == "explore-day-trading"
    assert args.family == "asia_europe_transition_daytype_reclaim_research"
    assert args.count == 2
    assert args.reference_candidate == "AF-CAND-0414"
    assert args.max_materialized == 3


def test_parser_supports_day_trading_behavior_scan_command():
    parser = build_parser()

    args = parser.parse_args(
        [
            "scan-day-trading-behaviors",
            "--project-root",
            "C:\\agentic-forex",
            "--family",
            "europe_open_gap_drift_research",
            "--max-sources",
            "4",
            "--reference-candidate",
            "AF-CAND-0414",
            "--refresh-candidates",
            "--max-materialized",
            "2",
        ]
    )

    assert args.command == "scan-day-trading-behaviors"
    assert args.family == "europe_open_gap_drift_research"
    assert args.max_sources == 4
    assert args.reference_candidate == "AF-CAND-0414"
    assert args.refresh_candidates is True
    assert args.max_materialized == 2


def test_cli_runs_from_outside_project_directory(project_root, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    oanda_json = create_oanda_candles_json(tmp_path)
    external_cwd = tmp_path / "Outside Workspace"
    external_cwd.mkdir(parents=True, exist_ok=True)

    ingest = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentic_forex",
            "ingest-market",
            "--project-root",
            str(project_root),
            "--oanda-json",
            str(oanda_json),
        ],
        cwd=external_cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    discover = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentic_forex",
            "discover",
            "--project-root",
            str(project_root),
            "--question",
            "Build a scalping strategy for EUR/USD",
            "--mirror-path",
            str(mirror),
        ],
        cwd=external_cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    assert ingest.returncode == 0, ingest.stderr
    assert discover.returncode == 0, discover.stderr
    assert '"source": "oanda"' in ingest.stdout
    assert '"family": "scalping"' in discover.stdout


def test_goblin_startup_cli_prints_banner_and_remaining_plan(project_root, tmp_path):
    external_cwd = tmp_path / "Outside Workspace"
    external_cwd.mkdir(parents=True, exist_ok=True)

    startup = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentic_forex",
            "goblin-startup",
            "--project-root",
            str(project_root),
            "--focus",
            "AF-CAND-0733",
        ],
        cwd=external_cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    assert startup.returncode == 0, startup.stderr
    assert "Goblin startup" in startup.stdout
    assert "Remaining plan:" in startup.stdout
    assert "S1-P01" in startup.stdout
    assert "Recommended next:" in startup.stdout
    assert "AF-CAND-0733" in startup.stdout


def test_read_policy_blocks_sibling_paths(settings, tmp_path):
    sibling_root = tmp_path / "Investment Strategy" / "Forex"
    sibling_root.mkdir(parents=True, exist_ok=True)
    blocked_file = sibling_root / "source-of-truth.md"
    blocked_file.write_text("blocked", encoding="utf-8")

    policy = ReadPolicy(project_root=settings.project_root)
    with pytest.raises(ProjectIsolationError):
        policy.assert_allowed(blocked_file)


def test_source_tree_has_no_forbidden_project_imports():
    forbidden = ("forex_research", "investment_copilot")
    source_root = TEMPLATE_ROOT / "src" / "agentic_forex"
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} references forbidden sibling project token {token!r}"
