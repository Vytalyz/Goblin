from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from agentic_forex.config import Settings
from agentic_forex.goblin.models import (
    CheckpointRecord,
    ComparisonContract,
    GoblinProgramStatus,
    PhaseBlueprint,
    PhaseRecord,
    PhaseStatus,
)
from agentic_forex.utils.io import read_json, write_json

PHASE_BLUEPRINTS: list[PhaseBlueprint] = [
    PhaseBlueprint(
        phase_id="GOBLIN-P00",
        title="Program Foundation And Naming",
        objective="Create Goblin as the tracked umbrella program without destabilizing the current runtime kernel.",
        outputs=["Goblin master docs", "phase ledger", "naming ADR", "CLI alias plan"],
        expected_artifacts=["Goblin/PROGRAM.md", "Goblin/ROADMAP.md", "Goblin/state/program_status.json"],
        exit_criteria=[
            "Goblin exists as the canonical program layer.",
            "All later phases have dependency graphs and state files.",
        ],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P01",
        title="Four-Channel Truth Stack",
        objective="Replace the old three-layer hierarchy with a four-channel decision-specific truth stack.",
        dependencies=["GOBLIN-P00"],
        outputs=["truth-stack contract", "comparison matrix", "governance language update"],
        expected_artifacts=["Goblin/contracts/truth-stack.md", "Goblin/contracts/comparison-matrix.md"],
        exit_criteria=["Promotion logic references the correct comparison rule for each channel pair."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P02",
        title="Provenance And Artifact Contracts",
        objective="Make provenance a hard gate everywhere.",
        dependencies=["GOBLIN-P01"],
        outputs=["artifact provenance contract", "channel-owned artifact indexes"],
        expected_artifacts=["Goblin/contracts/artifact-provenance.md"],
        exit_criteria=["Ambiguous provenance becomes impossible in governed workflows."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P03",
        title="Time, Session, And Data Normalization",
        objective="Eliminate hidden ambiguity in time handling and source-specific data interpretation.",
        dependencies=["GOBLIN-P02"],
        outputs=["time/session contract", "research data contract", "data quality gates"],
        expected_artifacts=["Goblin/contracts/time-session-contract.md", "Goblin/contracts/research-data-contract.md"],
        exit_criteria=["All comparisons share the same declared time basis.", "OANDA research is reproducible."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P04",
        title="MT5 Harness And Executable Certification",
        objective="Make MT5 the authoritative executable validation layer for MT5-targeted deployment.",
        dependencies=["GOBLIN-P03"],
        outputs=["MT5 certification contract", "deterministic-vs-MT5 certification"],
        expected_artifacts=["Goblin/contracts/mt5-certification.md"],
        exit_criteria=["No MT5 replay is treated as authoritative without harness certification."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P05",
        title="Live Demo Observability And Broker Reconciliation",
        objective="Make live-demo evidence operationally trustworthy and externally reconcilable.",
        dependencies=["GOBLIN-P04"],
        outputs=[
            "runtime contract",
            "broker reconciliation pipeline",
            "execution cost contract",
            "statistical decision policy",
            "ops incident triggers",
        ],
        expected_artifacts=[
            "Goblin/contracts/live-demo-contract.md",
            "Goblin/contracts/broker-reconciliation.md",
            "Goblin/contracts/execution-cost-contract.md",
            "Goblin/contracts/statistical-decision-policy.md",
        ],
        exit_criteria=["Live/demo no longer relies only on EA audit files."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P06",
        title="Incident And Safety Envelope System",
        objective="Turn failures into governed incidents instead of narrative debates, with severity-driven suspension rules and SLA obligations tied to operational events.",
        dependencies=["GOBLIN-P05"],
        outputs=["incident severity matrix", "incident SLA contract", "updated incident response runbook"],
        expected_artifacts=[
            "Goblin/contracts/incident-severity-matrix.md",
            "Goblin/contracts/incident-sla.md",
            "Goblin/runbooks/INCIDENT_RESPONSE.md",
        ],
        exit_criteria=[
            "Any unexplained material delta opens or keeps open an incident.",
            "Incident severity drives suspension and closure evidence requirements, not operator discretion.",
            "IncidentRecord carries severity and SLA class.",
        ],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P07",
        title="Release, Approval, And Change Management",
        objective="Make every deployable artifact a governed release bundle with a declared deployment ladder state, so bundle approval and operational readiness are never conflated.",
        dependencies=["GOBLIN-P05"],
        outputs=[
            "deployment bundle schema",
            "deployment ladder contract",
            "environment reproducibility contract",
            "approval boundary policy",
            "retention runbooks",
        ],
        expected_artifacts=[
            "Goblin/contracts/deployment-bundle.md",
            "Goblin/contracts/deployment-ladder.md",
            "Goblin/contracts/environment-reproducibility.md",
            "Goblin/runbooks/RELEASE_AND_ROLLBACK.md",
        ],
        exit_criteria=[
            "No live/demo attachment occurs without a deployable bundle and a declared ladder state.",
            "Config hash mismatch between bundle and attach triggers a release integrity incident.",
        ],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P08",
        title="Investigation And Evaluation Framework",
        objective="Add a Holmes-style, repo-native investigation and eval layer without making it critical-path runtime.",
        dependencies=["GOBLIN-P06"],
        outputs=["investigation scenarios", "evaluation suite", "benchmark history"],
        expected_artifacts=["Goblin/contracts/investigation-trace.md", "Goblin/contracts/evaluation-suite.md"],
        exit_criteria=["Serious incidents have reproducible investigation packs."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P09",
        title="Strategy Methodology, Search-Bias, And Experiment Governance",
        objective="Improve strategy quality without repeating the same research-control mistakes, with experiment budgeting that enforces search discipline rather than documenting it.",
        dependencies=["GOBLIN-P08"],
        outputs=[
            "methodology rubric",
            "strategy rationale cards",
            "experiment accounting ledger with budget enforcement",
        ],
        expected_artifacts=["Goblin/contracts/strategy-rationale-card.md", "Goblin/contracts/experiment-accounting.md"],
        exit_criteria=[
            "No live/demo candidate exists without a rationale card and experiment lineage.",
            "Experiment accounting captures the budget consumed and whether suspension thresholds were hit.",
        ],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P10",
        title="Portfolio And Candidate Strategy Program",
        objective="Resume and improve strategy search under repaired governance, with promotion decisions anchored to the statistical decision policy and deployment ladder.",
        dependencies=["GOBLIN-P09"],
        outputs=["candidate scorecard", "deployment profile", "promotion decision packet"],
        expected_artifacts=["Goblin/contracts/candidate-scorecard.md", "Goblin/contracts/promotion-decision-packet.md"],
        exit_criteria=[
            "No improvement claim can hide deployment changes inside alpha claims.",
            "Promotion criteria reference statistical policy thresholds, not free-text judgment.",
            "Deployment ladder state is required in every promotion decision packet.",
        ],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P11",
        title="Governed ML And Self-Learning",
        objective="Add learning only after labels and provenance are trustworthy.",
        dependencies=["GOBLIN-P10"],
        outputs=["model registry", "label policy", "governed offline training cycle"],
        expected_artifacts=["Goblin/contracts/model-registry.md"],
        exit_criteria=["No online self-tuning exists in live/demo execution."],
    ),
    PhaseBlueprint(
        phase_id="GOBLIN-P12",
        title="Knowledge Store, Vector Memory, And Agentic Layer",
        objective="Add retrieval and richer agent support without turning them into the source of truth.",
        dependencies=["GOBLIN-P11"],
        outputs=["knowledge lineage model", "retrieval index", "bounded Goblin agent roles"],
        expected_artifacts=["Goblin/contracts/knowledge-lineage.md", "Goblin/contracts/retrieval-policy.md"],
        exit_criteria=["Agentic features do not weaken governance or runtime truth."],
    ),
]

TRUTH_CONTRACTS: list[ComparisonContract] = [
    ComparisonContract(
        left_channel="research_backtest",
        right_channel="mt5_replay",
        enforcement="structural_consistency",
        decision_scope="research-to-executable validation",
        notes=[
            "Research and MT5 do not need tick-for-tick agreement.",
            "They must agree on rationale, session structure, regime sensitivity, and non-catastrophic behavior.",
        ],
    ),
    ComparisonContract(
        left_channel="mt5_replay",
        right_channel="live_demo",
        enforcement="strict_executable_parity",
        decision_scope="deployment-grade validation",
        notes=["Missing or extra trades on frozen windows are promotion-blocking unless incidented."],
    ),
    ComparisonContract(
        left_channel="live_demo",
        right_channel="broker_account_history",
        enforcement="strict_reconciliation",
        decision_scope="operational and financial reconciliation",
        notes=["Broker/account history is the independent source for what actually happened externally."],
    ),
]

PHASE_DETAILS: dict[str, dict[str, list[str]]] = {
    "GOBLIN-P00": {
        "build_items": [
            "Create the Goblin umbrella directory tree and machine-readable phase ledger.",
            "Preserve `src/agentic_forex` as the runtime kernel while introducing Goblin at the control-plane layer.",
            "Add the `goblin` CLI alias and the Goblin operator-orchestrator terminology to repo docs.",
            "Record the first authoritative checkpoint so later phases can resume from a known-good foundation.",
        ],
        "checkpoint_targets": [
            "Goblin directory tree exists under `/Goblin` with state, phases, contracts, decisions, templates, and runbooks.",
            "CLI exposes `goblin-init`, `goblin-status`, `goblin-phase-update`, and `goblin-checkpoint`.",
            "Phase state JSON exists for `GOBLIN-P00` through `GOBLIN-P12`.",
        ],
        "authoritative_artifacts": [
            "Goblin/PROGRAM.md",
            "Goblin/ROADMAP.md",
            "Goblin/state/program_status.json",
            "Goblin/state/phases/GOBLIN-P00.json",
            "Goblin/decisions/ADR-0001-goblin-umbrella-program.md",
            "src/agentic_forex/goblin/service.py",
            "src/agentic_forex/goblin/models.py",
        ],
        "regenerable_artifacts": [
            "Goblin/STATUS.md",
            "Goblin/phases/GOBLIN-P00.md",
        ],
    },
    "GOBLIN-P01": {
        "build_items": [
            "Define the four decision-specific truth channels: research, MT5 replay, live demo, and broker/account reconciliation.",
            "Write the comparison matrix that distinguishes structural consistency from executable parity and strict reconciliation.",
            "Update governance wording so channels are no longer treated as interchangeable or globally identical.",
        ],
        "checkpoint_targets": [
            "Truth-stack contract is written and accepted as the repo-wide reference.",
            "Comparison rules exist for research <-> MT5, MT5 <-> live, and live <-> broker.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/truth-stack.md",
            "Goblin/contracts/comparison-matrix.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P01.md",
        ],
    },
    "GOBLIN-P02": {
        "build_items": [
            "Define artifact provenance fields and explicit `evidence_channel` tagging across governed artifacts.",
            "Replace heuristic evidence discovery with channel-owned indexes and immutable run identity.",
            "Treat ambiguous provenance as a hard validation failure rather than an operator warning.",
        ],
        "checkpoint_targets": [
            "Artifact provenance contract is written and referenced from validation and incident flows.",
            "Channel-owned artifact resolution replaces wildcard audit discovery in governed paths.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/artifact-provenance.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P02.md",
        ],
    },
    "GOBLIN-P03": {
        "build_items": [
            "Define a canonical time/session model for broker offsets, DST boundaries, holidays, and overlap windows.",
            "Freeze the reproducibility contract for OANDA research downloads including price component and alignment settings.",
            "Add data-quality gates for missing bars, duplicates, spread anomalies, session gaps, and malformed exports.",
        ],
        "checkpoint_targets": [
            "Time/session contract exists and declares the comparison time basis.",
            "Research-data contract exists and captures the OANDA query settings that make research reproducible.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/time-session-contract.md",
            "Goblin/contracts/research-data-contract.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P03.md",
        ],
    },
    "GOBLIN-P04": {
        "build_items": [
            "Define the MT5 certification envelope including tester mode, delay model, tick provenance, and symbol/account snapshots.",
            "Require baseline known-good reproduction before treating incident replays as trustworthy.",
            "Classify deterministic engines as `deployment_grade`, `research_only`, or `untrusted` based on MT5 parity.",
        ],
        "checkpoint_targets": [
            "MT5 certification contract exists and includes tick provenance.",
            "Harness trust status is separated from candidate alpha claims.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/mt5-certification.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P04.md",
        ],
    },
    "GOBLIN-P05": {
        "build_items": [
            "Define live attach manifests, runtime summaries, heartbeats, and broker/account reconciliation outputs.",
            "Separate EA audit files from independent broker reconciliation so live truth is not self-referential.",
            "Codify chaos and failure scenarios for terminal closure, sleep/wake, account changes, and audit gaps.",
            "Author execution-cost-contract defining the single cross-channel execution assumption layer.",
            "Author statistical-decision-policy defining strategy-class-based thresholds for incidents, promotion, and variance bands.",
        ],
        "checkpoint_targets": [
            "Live-demo contract exists with runtime observability requirements.",
            "Broker reconciliation contract exists, distinguishes MT5 primitives, and is treated as external truth.",
            "Execution cost contract exists and governs spread, commission, slippage, and fill assumptions across all channels.",
            "Statistical decision policy exists with strategy-class-based thresholds for promotion and incident classification.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/live-demo-contract.md",
            "Goblin/contracts/broker-reconciliation.md",
            "Goblin/contracts/execution-cost-contract.md",
            "Goblin/contracts/statistical-decision-policy.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P05.md",
        ],
    },
    "GOBLIN-P06": {
        "build_items": [
            "Define the incident severity matrix: S1-S4 levels, incident type classification, suspension rules, and candidate inheritance.",
            "Define incident SLAs as operational-event-relative deadlines, not wall-clock times.",
            "Update the incident response runbook to reference severity levels and required closure evidence by severity.",
            "Integrate statistical decision policy thresholds into incident open/close triggers.",
            "Add severity and SLA class fields to the IncidentRecord model.",
            "Specify how related candidates inherit safety blocks when they depend on an untrusted validation stack.",
        ],
        "checkpoint_targets": [
            "Severity matrix classifies all incident types with default severity and escalation rules.",
            "SLA contract uses operational-event-relative deadlines with required closure evidence per severity.",
            "Incident response runbook references severity matrix and SLA contract.",
            "IncidentRecord model carries severity and SLA class fields.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/incident-severity-matrix.md",
            "Goblin/contracts/incident-sla.md",
            "Goblin/runbooks/INCIDENT_RESPONSE.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P06.md",
        ],
    },
    "GOBLIN-P07": {
        "build_items": [
            "Define the deployment bundle, approval boundaries, rollback criteria, and immutable evidence retention policy.",
            "Define the deployment ladder: shadow_only, limited_demo, observed_demo, challenger_demo, eligible_for_replacement.",
            "Enforce that bundle approval does not imply operational readiness; every live/demo attach must reference both bundle and ladder state.",
            "Define environment reproducibility requirements: terminal build pinning, config drift detection, secrets location policy, and critical-state backup.",
            "Add ladder state to LiveAttachManifest and incident closure packet models.",
            "Document the manual approval surfaces required before demo or production-facing changes.",
        ],
        "checkpoint_targets": [
            "Deployment ladder defines all five states with verifiable transition requirements.",
            "Environment reproducibility covers terminal build pinning, config drift, and secrets policy.",
            "Release and rollback runbook references the ladder and bundle contracts.",
            "LiveAttachManifest carries ladder state.",
            "Bundle approval cannot be treated as permission to advance the ladder.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/deployment-bundle.md",
            "Goblin/contracts/deployment-ladder.md",
            "Goblin/contracts/environment-reproducibility.md",
            "Goblin/runbooks/RELEASE_AND_ROLLBACK.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P07.md",
        ],
    },
    "GOBLIN-P08": {
        "build_items": [
            "Define a repo-native investigation framework inspired by Holmes-style structured investigations and eval loops.",
            "Make incident diagnosis reproducible through scenarios, traces, and benchmark history.",
            "Keep investigation tooling advisory and outside the critical runtime path.",
        ],
        "checkpoint_targets": [
            "Investigation trace contract exists.",
            "Evaluation suite contract exists and separates deterministic regression from replay-backed reliability runs.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/investigation-trace.md",
            "Goblin/contracts/evaluation-suite.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P08.md",
        ],
    },
    "GOBLIN-P09": {
        "build_items": [
            "Translate the strategy book into a methodology rubric rather than a trading oracle.",
            "Add strategy rationale cards and search-bias controls at the family level.",
            "Add experiment budgeting: per-family budget caps, mutation depth limits, and suspension thresholds after failed refinements.",
            "Define invalid comparison rules: prohibit in-sample vs out-of-sample comparisons and cross-window comparisons without regime accounting.",
            "Use statistical decision policy thresholds as the research floor.",
            "Prevent candidate churn from hiding multiple-testing or experiment-lineage risk.",
        ],
        "checkpoint_targets": [
            "Strategy rationale card contract exists.",
            "Experiment-accounting contract captures per-family budget, mutation depth, invalid comparison rules, and suspension thresholds.",
            "Both contracts reference the statistical decision policy as the shared research floor.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/strategy-rationale-card.md",
            "Goblin/contracts/experiment-accounting.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P09.md",
        ],
    },
    "GOBLIN-P10": {
        "build_items": [
            "Resume governed strategy search only after truth-stack, incident controls, and experiment governance are in place.",
            "Separate alpha quality from deployment fit through candidate scorecards, deployment profiles, and risk overlays.",
            "Enforce that promotion packets reference statistical decision policy keys, not free-text judgment.",
            "Enforce that promotion packets reference the candidate's current deployment ladder state.",
            "Block promotion for candidates below observed_demo ladder state.",
            "Enforce benchmark/challenger rules and promotion packets across overlap and gap lanes.",
            "Ensure deployment-fit changes that cross declared thresholds require a new bundle, not a promotion continuation.",
        ],
        "checkpoint_targets": [
            "Candidate scorecard contract exists.",
            "Promotion decision packet exists and distinguishes alpha from deployment fit.",
            "Promotion decision packet cites statistical policy keys for every criterion.",
            "Promotion decision packet cites the candidate's deployment ladder state.",
            "Promotion is blocked for candidates below observed_demo.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/candidate-scorecard.md",
            "Goblin/contracts/promotion-decision-packet.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P10.md",
        ],
    },
    "GOBLIN-P11": {
        "build_items": [
            "Add a governed model registry and trusted label policy for offline learning only.",
            "Start with low-risk ML layers such as anomaly detection and regime classification.",
            "Require offline validation, holdouts, and MT5-compatible replay if model output touches live decision logic.",
        ],
        "checkpoint_targets": [
            "Model registry contract exists.",
            "Offline-only self-learning rule is documented and linked to governance.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/model-registry.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P11.md",
        ],
    },
    "GOBLIN-P12": {
        "build_items": [
            "Add a structured knowledge store first, then optional vector retrieval with provenance-cited outputs.",
            "Define bounded Goblin agent roles that accelerate review without becoming the source of truth.",
            "Keep the repo operational even if Codex is closed or the Goblin agent layer is unavailable.",
        ],
        "checkpoint_targets": [
            "Knowledge-lineage contract exists.",
            "Retrieval-policy contract exists and keeps vector memory advisory only.",
        ],
        "authoritative_artifacts": [
            "Goblin/contracts/knowledge-lineage.md",
            "Goblin/contracts/retrieval-policy.md",
        ],
        "regenerable_artifacts": [
            "Goblin/phases/GOBLIN-P12.md",
        ],
    },
}


def initialize_goblin_program(settings: Settings, *, refresh_docs: bool = False) -> GoblinProgramStatus:
    paths = settings.paths()
    paths.ensure_directories()

    _write_if_missing_or_refresh(paths.goblin_dir / "PROGRAM.md", _program_markdown(), refresh_docs)
    _write_if_missing_or_refresh(paths.goblin_dir / "ROADMAP.md", _roadmap_markdown(), refresh_docs)
    _write_if_missing_or_refresh(paths.goblin_contracts_dir / "truth-stack.md", _truth_stack_markdown(), refresh_docs)
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "comparison-matrix.md", _comparison_matrix_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "artifact-provenance.md", _artifact_provenance_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "research-data-contract.md", _research_contract_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "time-session-contract.md", _time_session_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "mt5-certification.md", _mt5_certification_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "live-demo-contract.md", _live_demo_contract_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "broker-reconciliation.md", _broker_reconciliation_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "execution-cost-contract.md", _execution_cost_contract_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "statistical-decision-policy.md",
        _statistical_decision_policy_markdown(),
        refresh_docs,
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "incident-severity-matrix.md", _incident_severity_matrix_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(paths.goblin_contracts_dir / "incident-sla.md", _incident_sla_markdown(), refresh_docs)
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "deployment-ladder.md", _deployment_ladder_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "environment-reproducibility.md",
        _environment_reproducibility_markdown(),
        refresh_docs,
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "deployment-bundle.md", _deployment_bundle_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "investigation-trace.md", _investigation_trace_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "evaluation-suite.md", _evaluation_suite_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "strategy-rationale-card.md", _strategy_rationale_card_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "experiment-accounting.md", _experiment_accounting_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "strategy-methodology-rubric.md",
        _strategy_methodology_rubric_markdown(),
        refresh_docs,
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "candidate-scorecard.md", _candidate_scorecard_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "promotion-decision-packet.md", _promotion_decision_packet_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "model-registry.md", _model_registry_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "knowledge-lineage.md", _knowledge_lineage_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "retrieval-policy.md", _retrieval_policy_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_contracts_dir / "operator-orchestrator-split.md",
        _operator_orchestrator_split_markdown(),
        refresh_docs,
    )
    _write_if_missing_or_refresh(paths.goblin_templates_dir / "ADR_TEMPLATE.md", _adr_template_markdown(), refresh_docs)
    _write_if_missing_or_refresh(
        paths.goblin_templates_dir / "PHASE_RECORD_TEMPLATE.md", _phase_template_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_templates_dir / "phase_record.example.json", _phase_record_example_json(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_templates_dir / "checkpoint_record.example.json", _checkpoint_record_example_json(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_runbooks_dir / "RESUME_PHASE.md", _resume_runbook_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_runbooks_dir / "INCIDENT_RESPONSE.md", _incident_runbook_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_runbooks_dir / "RELEASE_AND_ROLLBACK.md", _release_runbook_markdown(), refresh_docs
    )
    _write_if_missing_or_refresh(
        paths.goblin_decisions_dir / "ADR-0001-goblin-umbrella-program.md", _adr_0001_markdown(), refresh_docs
    )

    existing = _load_existing_phase_records(settings)
    completed_ids = {phase_id for phase_id, record in existing.items() if record.status == "completed"}
    phase_records: list[PhaseRecord] = []
    for blueprint in PHASE_BLUEPRINTS:
        phase_details = PHASE_DETAILS.get(blueprint.phase_id, {})
        record_path = paths.goblin_phase_state_dir / f"{blueprint.phase_id}.json"
        current = existing.get(blueprint.phase_id)
        phase_record = PhaseRecord(
            phase_id=blueprint.phase_id,
            title=blueprint.title,
            objective=blueprint.objective,
            status=current.status if current else _default_phase_status(blueprint, completed_ids),
            dependencies=list(blueprint.dependencies),
            inputs=list(blueprint.inputs),
            build_items=list(phase_details.get("build_items", current.build_items if current else [])),
            outputs=list(blueprint.outputs),
            expected_artifacts=list(blueprint.expected_artifacts),
            checkpoint_targets=list(
                phase_details.get("checkpoint_targets", current.checkpoint_targets if current else [])
            ),
            authoritative_artifacts=list(
                phase_details.get("authoritative_artifacts", current.authoritative_artifacts if current else [])
            ),
            regenerable_artifacts=list(
                phase_details.get("regenerable_artifacts", current.regenerable_artifacts if current else [])
            ),
            last_checkpoint=current.last_checkpoint if current else None,
            idempotency_key=current.idempotency_key if current else f"goblin:{blueprint.phase_id}",
            rerun_mode=current.rerun_mode if current else blueprint.rerun_mode,
            resume_command=current.resume_command
            if current
            else f"goblin goblin-phase-update --phase-id {blueprint.phase_id} --status in_progress",
            verify_command=current.verify_command if current else "goblin goblin-status",
            blockers=list(current.blockers) if current else [],
            owner=current.owner if current else blueprint.owner,
            started_at=current.started_at if current else None,
            updated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            completed_at=current.completed_at if current else None,
            exit_criteria=list(blueprint.exit_criteria),
            acceptance_result=dict(current.acceptance_result) if current else {},
            notes=list(current.notes) if current else [],
            record_path=record_path,
        )
        write_json(record_path, phase_record.model_dump(mode="json"))
        _write_if_missing_or_refresh(
            paths.goblin_phases_dir / f"{blueprint.phase_id}.md", _phase_markdown(blueprint), refresh_docs
        )
        phase_records.append(phase_record)
        if phase_record.status == "completed":
            completed_ids.add(phase_record.phase_id)

    status = _build_program_status(settings, phase_records)
    _write_status_markdown(settings, status)
    write_json(paths.goblin_program_status_path, status.model_dump(mode="json"))
    return status


def get_goblin_program_status(settings: Settings) -> GoblinProgramStatus:
    initialize_goblin_program(settings, refresh_docs=False)
    phase_records = [
        PhaseRecord.model_validate(read_json(path))
        for path in sorted(settings.paths().goblin_phase_state_dir.glob("GOBLIN-P*.json"))
    ]
    phase_records = _refresh_dependency_statuses(phase_records)
    for record in phase_records:
        write_json(record.record_path, record.model_dump(mode="json"))
    status = _build_program_status(settings, phase_records)
    _write_status_markdown(settings, status)
    write_json(settings.paths().goblin_program_status_path, status.model_dump(mode="json"))
    return status


def update_goblin_phase(
    settings: Settings,
    *,
    phase_id: str,
    status: PhaseStatus | None = None,
    blocker: str | None = None,
    note: str | None = None,
    owner: str | None = None,
    acceptance_updates: dict[str, object] | None = None,
) -> PhaseRecord:
    initialize_goblin_program(settings, refresh_docs=False)
    record_path = settings.paths().goblin_phase_state_dir / f"{phase_id}.json"
    record = PhaseRecord.model_validate(read_json(record_path))
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if status is not None:
        record.status = status
        if status == "in_progress" and record.started_at is None:
            record.started_at = now
        if status == "completed":
            record.completed_at = now
            if record.started_at is None:
                record.started_at = now
        elif status != "completed":
            record.completed_at = None
    if owner is not None:
        record.owner = owner
    if blocker and blocker not in record.blockers:
        record.blockers.append(blocker)
    if note:
        record.notes.append(note)
    if acceptance_updates:
        record.acceptance_result.update(acceptance_updates)
    record.updated_at = now
    write_json(record_path, record.model_dump(mode="json"))
    refreshed = get_goblin_program_status(settings)
    return next(item for item in refreshed.phase_records if item.phase_id == phase_id)


def create_goblin_checkpoint(
    settings: Settings,
    *,
    phase_id: str,
    checkpoint_id: str | None,
    summary: str,
    authoritative_artifacts: list[str] | None = None,
    regenerable_artifacts: list[str] | None = None,
    status: PhaseStatus | None = None,
) -> CheckpointRecord:
    phase_record = update_goblin_phase(settings, phase_id=phase_id, status=status)
    resolved_id = checkpoint_id or f"{phase_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    checkpoint_dir = settings.paths().goblin_checkpoints_dir / phase_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / f"{resolved_id}.json"
    checkpoint = CheckpointRecord(
        checkpoint_id=resolved_id,
        phase_id=phase_id,
        summary=summary,
        authoritative_artifacts=list(authoritative_artifacts or []),
        regenerable_artifacts=list(regenerable_artifacts or []),
        status_at_checkpoint=phase_record.status,
        checkpoint_path=checkpoint_path,
    )
    write_json(checkpoint_path, checkpoint.model_dump(mode="json"))
    phase_record.last_checkpoint = str(checkpoint_path)
    phase_record.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    write_json(phase_record.record_path, phase_record.model_dump(mode="json"))
    get_goblin_program_status(settings)
    return checkpoint


def _load_existing_phase_records(settings: Settings) -> dict[str, PhaseRecord]:
    records: dict[str, PhaseRecord] = {}
    for path in settings.paths().goblin_phase_state_dir.glob("GOBLIN-P*.json"):
        try:
            records[path.stem] = PhaseRecord.model_validate(read_json(path))
        except Exception:
            continue
    return records


def _default_phase_status(blueprint: PhaseBlueprint, completed_ids: set[str]) -> PhaseStatus:
    if not blueprint.dependencies:
        return "ready"
    return "ready" if all(dep in completed_ids for dep in blueprint.dependencies) else "not_started"


def _build_program_status(settings: Settings, phase_records: list[PhaseRecord]) -> GoblinProgramStatus:
    counts = Counter(record.status for record in phase_records)
    ready = [record.phase_id for record in phase_records if record.status == "ready"]
    blocked = [record.phase_id for record in phase_records if record.status in {"blocked", "incident_open"}]
    current = next((record.phase_id for record in phase_records if record.status == "in_progress"), None)
    if current is None:
        current = ready[0] if ready else None
    return GoblinProgramStatus(
        total_phases=len(phase_records),
        phase_counts=dict(counts),
        ready_phase_ids=ready,
        blocked_phase_ids=blocked,
        current_phase_id=current,
        phase_records=phase_records,
        program_status_path=settings.paths().goblin_program_status_path,
        status_markdown_path=settings.paths().goblin_dir / "STATUS.md",
        roadmap_markdown_path=settings.paths().goblin_dir / "ROADMAP.md",
        program_markdown_path=settings.paths().goblin_dir / "PROGRAM.md",
    )


def _refresh_dependency_statuses(phase_records: list[PhaseRecord]) -> list[PhaseRecord]:
    completed = {record.phase_id for record in phase_records if record.status == "completed"}
    refreshed: list[PhaseRecord] = []
    for record in phase_records:
        if record.status == "not_started" and all(dep in completed for dep in record.dependencies):
            record.status = "ready"
            record.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        refreshed.append(record)
    return refreshed


def _write_status_markdown(settings: Settings, status: GoblinProgramStatus) -> None:
    lines = [
        "# Goblin Status",
        "",
        f"- Generated UTC: `{status.generated_utc}`",
        f"- Current phase: `{status.current_phase_id or 'none'}`",
        f"- Ready phases: `{', '.join(status.ready_phase_ids) if status.ready_phase_ids else 'none'}`",
        f"- Blocked phases: `{', '.join(status.blocked_phase_ids) if status.blocked_phase_ids else 'none'}`",
        "",
        "## Companion Tracking",
        "",
        "- Implementation reality: `Goblin/IMPLEMENTATION_TRACKER.md`",
        "- Maturity model: `Goblin/MATURITY.md`",
        "- Evolution record: `Goblin/EVOLUTION.md`",
        "- Future rename path: `Goblin/TAKEOVER_PLAN.md`",
        "",
        "## Operating Rule",
        "",
        "- Work one phase at a time in sequence.",
        "- When a phase reaches its exit criteria, update the tracking documents and stop for explicit user approval before starting the next phase.",
        "",
        "## Phase Counts",
    ]
    for key in sorted(status.phase_counts):
        lines.append(f"- `{key}`: {status.phase_counts[key]}")
    lines.extend(
        [
            "",
            "## Phase Table",
            "",
            "| Phase | Status | Owner | Last Checkpoint | Resume | Blockers |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for record in status.phase_records:
        blockers = "; ".join(record.blockers) if record.blockers else "none"
        lines.append(
            f"| `{record.phase_id}` | `{record.status}` | `{record.owner}` | `{record.last_checkpoint or 'none'}` | "
            f"`{record.resume_command}` | {blockers} |"
        )
    (settings.paths().goblin_dir / "STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_if_missing_or_refresh(path, content: str, refresh: bool) -> None:
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _program_markdown() -> str:
    return """# Goblin Program

Goblin is the umbrella reliability, validation, and intelligence program for the forex agentic system. It is the tracked control-plane program that sits over the existing deterministic kernel in `src/agentic_forex`.

## Program Intent

Goblin exists to stop truth drift, preserve executable validation, govern incidents, and make long-running strategy work resumable phase by phase. It is designed so the repo can recover cleanly after interruptions, usage limits, or failed runs.

## Control Split

- `GoblinOrchestrator`: machine-facing workflow controller for phase sequencing, dependency gating, idempotent reruns, checkpoints, and resumability.
- `GoblinOperator`: human/Codex-facing supervisory layer for evidence assembly, status summaries, approval surfaces, incident framing, and decision support.

## Decision-Specific Truth Stack

- `research_backtest`: research truth
- `mt5_replay`: executable validation truth
- `live_demo`: operational truth
- `broker_account_history`: reconciliation truth

These channels do not answer the same question, and Goblin does not require them to match in the same way. Research <-> MT5 is structural, MT5 <-> live is strict executable parity, and live <-> broker is strict reconciliation.

## Phase Execution Rules

- Every phase is checkpointed.
- Every phase can be resumed from its last verified checkpoint.
- Authoritative artifacts must be preserved; regenerable artifacts may be rebuilt.
- A phase cannot be claimed complete until its exit criteria and acceptance checks are satisfied.
- Any material unexplained delta between required channels must open or keep open an incident.

## Kernel Boundary

Goblin is the umbrella control plane. The existing `src/agentic_forex` package remains the deterministic runtime kernel until a later migration phase explicitly replaces it. The repo must remain valid and resumable even if Codex is closed.
"""


def _roadmap_markdown() -> str:
    lines = [
        "# Goblin Roadmap",
        "",
        "This roadmap is the tracked execution order for the Goblin V3 program.",
        "",
        "| Phase | Title | Depends On | Primary Deliverable |",
        "| --- | --- | --- | --- |",
    ]
    for blueprint in PHASE_BLUEPRINTS:
        deps = ", ".join(blueprint.dependencies) if blueprint.dependencies else "none"
        deliverable = blueprint.expected_artifacts[0] if blueprint.expected_artifacts else "n/a"
        lines.append(f"| `{blueprint.phase_id}` | {blueprint.title} | `{deps}` | `{deliverable}` |")
    return "\n".join(lines) + "\n"


def _phase_markdown(blueprint: PhaseBlueprint) -> str:
    phase_details = PHASE_DETAILS.get(blueprint.phase_id, {})
    deps = ", ".join(blueprint.dependencies) if blueprint.dependencies else "none"
    inputs = "\n".join(f"- {item}" for item in blueprint.inputs) or "- none"
    build_items = "\n".join(f"- {item}" for item in phase_details.get("build_items", [])) or "- none"
    outputs = "\n".join(f"- {item}" for item in blueprint.outputs) or "- none"
    artifacts = "\n".join(f"- `{item}`" for item in blueprint.expected_artifacts) or "- none"
    checkpoint_targets = "\n".join(f"- {item}" for item in phase_details.get("checkpoint_targets", [])) or "- none"
    authoritative_artifacts = (
        "\n".join(f"- `{item}`" for item in phase_details.get("authoritative_artifacts", [])) or "- none"
    )
    regenerable_artifacts = (
        "\n".join(f"- `{item}`" for item in phase_details.get("regenerable_artifacts", [])) or "- none"
    )
    exit_criteria = "\n".join(f"- {item}" for item in blueprint.exit_criteria) or "- none"
    return (
        f"# {blueprint.phase_id}: {blueprint.title}\n\n"
        f"## Objective\n\n{blueprint.objective}\n\n"
        f"## Dependencies\n\n- `{deps}`\n\n"
        f"## Inputs\n\n{inputs}\n\n"
        f"## Build Scope\n\n{build_items}\n\n"
        f"## Outputs\n\n{outputs}\n\n"
        f"## Expected Artifacts\n\n{artifacts}\n\n"
        f"## Checkpoint Targets\n\n{checkpoint_targets}\n\n"
        f"## Authoritative Artifacts\n\n{authoritative_artifacts}\n\n"
        f"## Regenerable Artifacts\n\n{regenerable_artifacts}\n\n"
        f"## Resume And Verify\n\n"
        f"- Resume: `goblin goblin-phase-update --phase-id {blueprint.phase_id} --status in_progress`\n"
        f"- Verify: `goblin goblin-status`\n"
        f"- Rerun mode: `{blueprint.rerun_mode}`\n\n"
        f"## Exit Criteria\n\n{exit_criteria}\n"
    )


def _truth_stack_markdown() -> str:
    return """# Truth Stack

Goblin uses a four-channel decision-specific truth stack:

- `research_backtest`: research truth
- `mt5_replay`: executable validation truth
- `live_demo`: operational truth
- `broker_account_history`: reconciliation truth

No single channel is globally authoritative for every decision. Each channel answers a specific question, and each comparison pair uses the contract appropriate to that question.

## Channel Questions

- `research_backtest`: is there a plausible edge worth studying?
- `mt5_replay`: does the MT5 implementation behave credibly enough to deploy in MT5?
- `live_demo`: did the attached EA behave correctly in the real runtime environment?
- `broker_account_history`: what actually happened externally at the broker/account layer?
"""


def _comparison_matrix_markdown() -> str:
    lines = [
        "# Comparison Matrix",
        "",
        "Use the right comparison contract for the decision being made. Structural consistency is looser than executable parity, and executable parity is looser than broker reconciliation only in scope, not in seriousness.",
        "",
        "| Left | Right | Enforcement | Decision Scope |",
        "| --- | --- | --- | --- |",
    ]
    for contract in TRUTH_CONTRACTS:
        lines.append(
            f"| `{contract.left_channel}` | `{contract.right_channel}` | `{contract.enforcement}` | {contract.decision_scope} |"
        )
    lines.extend(
        [
            "",
            "## Enforcement Notes",
            "",
            "- `research_backtest <-> mt5_replay`: structural consistency only. Do not demand identical fills or timestamps.",
            "- `mt5_replay <-> live_demo`: strict executable parity on frozen windows. Missing or extra trades are incident triggers.",
            "- `live_demo <-> broker_account_history`: strict reconciliation. Broker/account evidence is the independent external ledger.",
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact_provenance_markdown() -> str:
    return """# Artifact Provenance

Every governed artifact must declare:

- `candidate_id`
- `run_id`
- `artifact_origin`
- `evidence_channel`
- `terminal_id`
- `terminal_build`
- `broker_server`
- `symbol`
- `timezone_basis`
- `created_at_utc`
- `artifact_hash`

## Rules

- Promotion, incident, and review workflows must consume explicit artifact references or channel-owned indexes only.
- Replay artifacts cannot be treated as live/demo evidence.
- Missing provenance fields are validation failures.
- Ambiguous provenance is a validation failure, not a warning.
"""


def _research_contract_markdown() -> str:
    return """# Research Data Contract

The OANDA-based research contract must freeze:

- `instrument`
- `price_component`
- `granularity`
- `smooth`
- `include_first`
- `daily_alignment`
- `alignment_timezone`
- `weekly_alignment`
- `utc_normalization_policy`

## Usage

- OANDA remains the canonical research source.
- Research artifacts are valid only when the acquisition configuration is frozen and recorded.
- OANDA ingest and backfill outputs must record the frozen acquisition contract inside their provenance payloads.
- Research truth must not be asked to prove the same thing as MT5 executable validation.
"""


def _time_session_markdown() -> str:
    return """# Time Session Contract

The canonical time/session contract must define:

- broker timezone and offset policy
- comparison time basis
- London/New York overlap definitions
- DST transition handling
- holiday policy
- market-open and market-close normalization

## Validation Use

- All cross-channel comparisons must declare the same time basis before they can be trusted.
- Truth-alignment reports must surface any channel whose declared timezone basis differs from the comparison basis.
- Session drift is an incident trigger when it affects executable parity or live reconciliation.
"""


def _mt5_certification_markdown() -> str:
    return """# MT5 Certification

MT5 replay is the executable validation truth for MT5-targeted deployment.

## Required Metadata

- `tester_mode`
- `delay_model`
- `tick_provenance`
- `symbol_snapshot`
- `account_snapshot`
- `terminal_build`
- `broker_server_class`

## Minimum Certification Conditions

- baseline known-good reproduction passes
- expected trade count is within tolerance
- expected session/hour participation is within tolerance
- entry and exit sequencing is within tolerance
- no unexplained missing or extra trades exist on frozen validation windows

## Deterministic Engine Status

- `deployment_grade`
- `research_only`
- `untrusted`
"""


def _live_demo_contract_markdown() -> str:
    return """# Live Demo Contract

Live demo is the operational truth channel.

## Required Outputs

- `LiveAttachManifest`
- `RuntimeSummary`
- `RuntimeHeartbeat`
- journal digest
- EA audit ledger
- inputs hash

## Required Controls

- terminal close detection
- sleep/wake detection
- account change detection
- algo-trading disablement detection
- stale audit detection
- incident auto-open on material runtime gaps
"""


def _broker_reconciliation_markdown() -> str:
    return """# Broker Reconciliation

Broker/account history is the reconciliation truth channel.

## Purpose

- verify what actually happened externally
- reconcile EA audit and live runtime output against broker-side orders, deals, and fills
- prevent the system from treating its own internal logs as final truth

## Minimum Checks

- matched trades
- missing broker trades
- extra broker trades
- cash PnL delta
- execution sequencing consistency
"""


def _execution_cost_contract_markdown() -> str:
    return """# Execution Cost Contract

Declares the single cross-channel execution assumption layer covering spread, commission, slippage,
fill delay, lot rounding, and partial-fill policy for all four truth channels.

See full specification in the authoritative contract file.
"""


def _statistical_decision_policy_markdown() -> str:
    return """# Statistical Decision Policy

Defines strategy-class-based thresholds (not candidate-calibrated) governing incident open/close
triggers, promotion gates, and ordinary variance bands.

See full specification in the authoritative contract file.
"""


def _incident_severity_matrix_markdown() -> str:
    return """# Incident Severity Matrix

Defines S1–S4 severity levels with operational-event-relative SLAs and suspension rules.

See full specification in the authoritative contract file.
"""


def _incident_sla_markdown() -> str:
    return """# Incident SLA

Defines response and resolution deadlines relative to operational events (not wall-clock time)
for each incident severity level.

See full specification in the authoritative contract file.
"""


def _deployment_ladder_markdown() -> str:
    return """# Deployment Ladder

Defines five deployment states: shadow_only, limited_demo, observed_demo, challenger_demo,
eligible_for_replacement. Separate from bundle approval.

See full specification in the authoritative contract file.
"""


def _environment_reproducibility_markdown() -> str:
    return """# Environment Reproducibility

Defines terminal build pinning, broker server class pinning, config drift detection via bundle
hashes, secrets policy, and critical state backup requirements.

See full specification in the authoritative contract file.
"""


def _deployment_bundle_markdown() -> str:
    return """# Deployment Bundle

Every live/demo attachment must reference a governed deployment bundle.

## Required Fields

- EA build hash
- inputs hash
- symbol assumptions
- account assumptions
- validation packet hash
- approval references
- rollback criteria

## Release Rule

No live/demo attachment is valid unless the deployment bundle and approval references are present.
"""


def _investigation_trace_markdown() -> str:
    return """# Investigation Trace

Goblin investigations are reproducible evidence traces, not conversational summaries.

## Canonical Outputs

- `Goblin/reports/investigations/<candidate_id>/<incident_id>/investigation_pack.json`
- scenario JSON files under `scenarios/`
- trace JSON files under `traces/`
- benchmark history snapshot referenced by the pack
- evaluation suite referenced by the pack

## Required Elements

- incident or scenario id
- input evidence references
- tool calls used
- intermediate classifications
- final classification
- confidence
- follow-up actions

## Scope

Investigation traces are advisory and diagnostic. They do not override validation or governance.
"""


def _evaluation_suite_markdown() -> str:
    return """# Evaluation Suite

The Goblin evaluation layer measures reliability and repeatability of investigations, validations, and comparison workflows.

## Canonical Outputs

- one evaluation suite per reproducible investigation pack
- benchmark history snapshot frozen from the incident packet used to build the suite
- scenario ids that distinguish deterministic checks from replay-backed and live-incident checks

## Core Scenario Types

- deterministic regression scenarios
- MT5 replay-backed scenarios
- live/runtime incident scenarios
- multi-iteration reliability runs
- benchmark history snapshots
"""


def _strategy_rationale_card_markdown() -> str:
    return """# Strategy Rationale Card

Every live/demo candidate family must have a rationale card.

## Required Fields

- why the edge should exist
- what invalidates the edge
- which market regimes should hurt it
- which execution assumptions it depends on
- what makes it non-deployable
"""


def _experiment_accounting_markdown() -> str:
    return """# Experiment Accounting

Goblin tracks search lineage to avoid hidden multiple-testing and experiment drift.

## Required Controls

- family-level trial ledger
- mutation lineage
- challenger versus blank-slate distinction
- over-search review for heavy-search families
- search-bias notes attached to promotion packets
"""


def _strategy_methodology_rubric_markdown() -> str:
    return """# Strategy Methodology Rubric

Goblin scores family-level strategy methodology before governed actions proceed.

## Required Dimensions

- thesis quality
- falsifiability quality
- regime specificity
- search discipline
- comparison integrity

## Enforcement

- rubric audits are family-level artifacts under `Goblin/reports/strategy_methodology_audits/`
- governed actions must be blocked when weighted rubric score is below the configured floor
- rubric evidence is advisory for iteration quality, not a substitute for candidate-level validation gates
"""


def _candidate_scorecard_markdown() -> str:
    return """# Candidate Scorecard

Candidate evaluation must separate alpha quality from deployment fit.

## Default Score Dimensions

- alpha quality
- robustness and stress behavior
- executable parity
- operational reliability
- deployment fit
"""


def _promotion_decision_packet_markdown() -> str:
    return """# Promotion Decision Packet

No candidate can be promoted without a complete decision packet.

## Required Components

- candidate scorecard
- truth alignment report
- strategy rationale card
- experiment accounting ledger reference
- strategy methodology audit reference
- search-bias narrative summary
- approval history
- deployment profile
- risk overlay
"""


def _model_registry_markdown() -> str:
    return """# Model Registry

Goblin ML is offline, governed, and approval-gated.

## Required Registry Fields

- training dataset snapshot
- label policy
- feature schema
- evaluation windows
- calibration results
- drift thresholds
- approval state

## Prohibitions

- live online self-tuning
- autonomous model promotion
- using ambiguous labels as training truth
"""


def _knowledge_lineage_markdown() -> str:
    return """# Knowledge Lineage

Goblin stores structured lineage for incidents, approvals, rationale, and evaluation history.

## Minimum Lineage Subjects

- incidents
- trade diff reports
- runtime summaries
- scorecards
- rationale cards
- approvals
- postmortems
"""


def _retrieval_policy_markdown() -> str:
    return """# Retrieval Policy

Vector retrieval is advisory and provenance-cited only.

## Rules

- structured ledgers remain the system of record
- vector similarity cannot promote, approve, or invalidate a candidate by itself
- retrieval outputs must cite source artifacts
- retrieval is secondary to validation and governance, never a replacement for them
"""


def _operator_orchestrator_split_markdown() -> str:
    return """# Operator And Orchestrator Split

Goblin uses both an orchestrator and an operator because they solve different problems.

## GoblinOrchestrator

- phase sequencing
- dependency gating
- checkpointing
- rerun and resume control
- machine-readable program status

## GoblinOperator

- evidence assembly
- incident framing
- approval support
- human-readable summaries
- decision support for Codex and human review
"""


def _adr_template_markdown() -> str:
    return """# ADR-XXXX: Title

## Context

## Decision

## Consequences
"""


def _phase_template_markdown() -> str:
    return """# GOBLIN-PXX: Title

## Objective

## Dependencies

## Inputs

## Build Scope

## Outputs

## Expected Artifacts

## Checkpoint Targets

## Authoritative Artifacts

## Regenerable Artifacts

## Resume And Verify

## Exit Criteria
"""


def _phase_record_example_json() -> str:
    return """{
  "phase_id": "GOBLIN-P00",
  "title": "Program Foundation And Naming",
  "objective": "Create Goblin as the tracked umbrella program without destabilizing the current runtime kernel.",
  "status": "ready",
  "dependencies": [],
  "inputs": [],
  "build_items": [
    "Create Goblin scaffolding."
  ],
  "outputs": [
    "Goblin master docs"
  ],
  "expected_artifacts": [
    "Goblin/PROGRAM.md"
  ],
  "checkpoint_targets": [
    "Goblin state exists."
  ],
  "authoritative_artifacts": [
    "Goblin/PROGRAM.md"
  ],
  "regenerable_artifacts": [
    "Goblin/STATUS.md"
  ],
  "last_checkpoint": null,
  "idempotency_key": "goblin:GOBLIN-P00",
  "rerun_mode": "resume_from_last_checkpoint",
  "resume_command": "goblin goblin-phase-update --phase-id GOBLIN-P00 --status in_progress",
  "verify_command": "goblin goblin-status",
  "blockers": [],
  "owner": "GoblinOrchestrator",
  "started_at": null,
  "updated_at": "2026-04-12T00:00:00Z",
  "completed_at": null,
  "exit_criteria": [
    "Goblin exists as the canonical program layer."
  ],
  "acceptance_result": {}
}
"""


def _checkpoint_record_example_json() -> str:
    return """{
  "checkpoint_id": "GOBLIN-P00-20260412T000000Z",
  "phase_id": "GOBLIN-P00",
  "created_utc": "2026-04-12T00:00:00Z",
  "summary": "Initialized Goblin scaffolding and phase ledger.",
  "authoritative_artifacts": [
    "Goblin/PROGRAM.md"
  ],
  "regenerable_artifacts": [
    "Goblin/STATUS.md"
  ],
  "status_at_checkpoint": "verification_pending",
  "checkpoint_path": "Goblin/checkpoints/GOBLIN-P00/GOBLIN-P00-20260412T000000Z.json"
}
"""


def _resume_runbook_markdown() -> str:
    return """# Resume Phase

1. Inspect `Goblin/STATUS.md`.
2. Open the phase record under `Goblin/state/phases/`.
3. Resume from `last_checkpoint` if present.
4. Re-run only regenerable artifacts unless the checkpoint says otherwise.
5. Record a new checkpoint after each verified boundary.
"""


def _incident_runbook_markdown() -> str:
    return """# Incident Response

1. Freeze artifacts.
2. Confirm provenance by channel.
3. Validate harness trust before trusting MT5 replay.
4. Compare the correct channel pairs with the correct contract.
5. Keep the incident open until unexplained deltas are attributed or reconciled.
"""


def _release_runbook_markdown() -> str:
    return """# Release And Rollback

Every deployable bundle must include:

- EA build hash
- inputs hash
- symbol and account assumptions
- validation packet hash
- approval references
- rollback criteria
"""


def _adr_0001_markdown() -> str:
    return """# ADR-0001: Goblin Umbrella Program

## Context

The repo already contains a deterministic `agentic_forex` kernel plus operator, campaign, portfolio, governance, runtime, and MT5 surfaces. A big-bang package rename would add migration risk before the reliability stack is stable.

## Decision

Adopt Goblin as the umbrella program identity at the documentation, control-plane, and workflow layer. Keep `src/agentic_forex` as the runtime kernel during early phases. Add a `goblin` CLI alias and Goblin tracking state under `/Goblin`.

## Consequences

- Goblin becomes the canonical program identity immediately.
- The Python namespace rename is deferred until platform stability and compatibility shims exist.
- Operator and orchestrator concerns stay separate.
"""
