from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentic_forex.utils.paths import ProjectPaths
from agentic_forex.utils.secrets import resolve_secret

ParityClass = Literal["m1_official", "tick_required"]
PortfolioSlotMode = Literal["active_candidate", "blank_slate_research"]
CodexExecutionMode = Literal[
    "disabled", "manual_or_readonly_summary", "app_automation_worktree", "app_automation_local"
]
LLMProvider = Literal["mock", "openai", "openai_legacy"]
CodexAutomationExecution = Literal["worktree", "local"]
CodexAutomationDefaultStatus = Literal["paused", "active"]


class LLMSettings(BaseModel):
    provider: LLMProvider = "mock"
    openai_model: str = "gpt-4.1-mini"
    temperature: float = 0.2
    api_key_env: str = "OPENAI_API_KEY"
    credential_targets: list[str] = Field(default_factory=lambda: ["openai-api-key"])
    planning_mode: Literal["deterministic_codex_default", "legacy_live_llm"] = "deterministic_codex_default"

    def api_key(self) -> str | None:
        return resolve_secret(env_var=self.api_key_env, credential_targets=self.credential_targets)

    @model_validator(mode="after")
    def _normalize_legacy_provider(self) -> LLMSettings:
        if self.provider == "openai":
            self.provider = "openai_legacy"
        if self.provider == "openai_legacy":
            self.planning_mode = "legacy_live_llm"
        return self


class OandaSettings(BaseModel):
    host: str = "https://api-fxpractice.oanda.com"
    token_env: str = "OANDA_API_TOKEN"
    credential_targets: list[str] = Field(
        default_factory=lambda: [
            "agentic-forex/oanda/practice",
            "forex-research/oanda/practice",
            "api-token@forex-research/oanda/practice",
        ]
    )
    default_instrument: str = "EUR_USD"
    default_granularity: str = "M1"
    price_component: str = "BA"
    default_count: int = 5000
    timeout_seconds: int = 30

    def api_token(self) -> str | None:
        return resolve_secret(env_var=self.token_env, credential_targets=self.credential_targets)


class DataSettings(BaseModel):
    instrument: str = "EUR_USD"
    canonical_source: str = "oanda"
    base_granularity: str = "M1"
    execution_granularity: str = "M1"
    raw_csv_glob: str = "*.csv"
    catalog_filename: str = "catalog.json"
    duckdb_filename: str = "market.duckdb"
    mt5_parity_db_filename: str = "mt5_parity.duckdb"
    economic_calendar_filename: str = "economic_calendar.parquet"
    quarantine_relevance_floor: float = 0.55
    discovery_relevance_floor: float = 0.72
    extraction_confidence_floor: float = 0.75
    supplemental_source_paths: list[str] = Field(default_factory=list)


class ValidationThresholds(BaseModel):
    out_of_sample_profit_factor_floor: float = 1.05
    expectancy_floor: float = 0.0
    minimum_test_trade_count: int = 100
    drawdown_review_trigger_pct: float = 12.0
    stress_spread_multiplier: float = 1.25
    stress_profit_factor_floor: float = 1.00
    stress_slippage_pips: float = 0.25
    stress_fill_delay_ms: int = 500
    walk_forward_windows: int = 3
    walk_forward_mode: Literal["equal_trade_windows", "anchored_time_windows"] = "anchored_time_windows"
    walk_forward_profit_factor_floor: float = 0.90
    walk_forward_min_trades_per_window: int = 10
    walk_forward_min_window_days: int = 7
    max_relative_drawdown_degradation_pct: float = 15.0
    deflated_sharpe_floor: float = 0.0
    cscv_partition_count: int = 8
    pbo_threshold: float = 0.35
    white_reality_check_bootstrap_samples: int = 250
    white_reality_check_block_size: int = 5
    white_reality_check_pvalue_threshold: float = 0.10
    white_reality_check_random_seed: int = 1729
    forward_min_trading_days: int = 10
    forward_min_trade_count: int = 25
    forward_profit_factor_floor: float = 1.0
    forward_expectancy_floor: float = 0.0
    forward_expectancy_degradation_limit_pct: float = 50.0
    parity_timestamp_tolerance_seconds: int = 90
    parity_close_timing_tolerance_seconds: int = 120
    parity_price_tolerance_pips: float = 0.30
    parity_fill_tolerance_pips: float = 0.50
    parity_min_match_rate: float = 0.80
    parity_max_unmatched_expected_rate: float = 0.20
    parity_max_unmatched_actual_rate: float = 0.20
    parity_min_closed_trades: int = 10


class CampaignSettings(BaseModel):
    default_family: str = "scalping"
    default_max_iterations: int = 2
    default_max_new_candidates: int = 8
    default_trial_cap_per_family: int = 50
    stop_on_review_eligible_provisional: bool = True
    max_mt5_parity_retries_per_candidate: int = 2
    max_shadow_forward_retries_per_candidate: int = 1
    max_total_operational_runs_per_campaign: int = 4
    default_throughput_target_count: int = 10
    max_rule_spec_reformulations_per_hypothesis: int = 2
    max_ea_spec_rewrites_per_candidate: int = 2
    max_compile_retries_per_candidate: int = 2
    max_smoke_retries_per_candidate: int = 1


class OrthogonalityMetadata(BaseModel):
    market_hypothesis: str
    trigger_family: str
    holding_profile: str
    session_profile: str
    regime_dependency: str

    def distance_to(self, other: OrthogonalityMetadata) -> int:
        return sum(
            1
            for field_name in (
                "market_hypothesis",
                "trigger_family",
                "holding_profile",
                "session_profile",
                "regime_dependency",
            )
            if getattr(self, field_name) != getattr(other, field_name)
        )


class ProgramLanePolicy(BaseModel):
    lane_id: str
    family: str = "scalping"
    hypothesis_class: str
    seed_candidate_id: str
    parity_class: ParityClass | None = None
    parity_class_assigned_by: str | None = None
    parity_class_assigned_at: str | None = None
    queue_kind: Literal["throughput", "promotion"] = "promotion"
    throughput_target_count: int = 0
    orthogonality_metadata: OrthogonalityMetadata | None = None
    required_evidence_tags: list[str] = Field(default_factory=list)
    compile_budget: int = 0
    smoke_budget: int = 0
    max_rule_spec_reformulations_per_hypothesis: int = 2
    max_ea_spec_rewrites_per_candidate: int = 2
    max_compile_retries_per_candidate: int = 2
    max_smoke_retries_per_candidate: int = 1
    max_steps: int = 8
    notes: list[str] = Field(default_factory=list)


class ProgramPolicySettings(BaseModel):
    active: bool = True
    max_lanes_per_run: int = 4
    require_seed_market_rationale: bool = True
    family_evidence_guard_enabled: bool = True
    archetype_retirement_enabled: bool = True
    archetype_retirement_lookback_days: int = 45
    archetype_retirement_failure_threshold: int = 7
    novelty_guard_enabled: bool = True
    novelty_similarity_threshold: float = 0.80
    approved_lanes: list[ProgramLanePolicy] = Field(default_factory=list)

    def invalid_throughput_lane_pairs(self, *, family: str | None = None) -> list[tuple[str, str]]:
        lanes = [
            lane
            for lane in self.approved_lanes
            if lane.queue_kind == "throughput" and (family is None or lane.family == family)
        ]
        invalid_pairs: list[tuple[str, str]] = []
        for index, left_lane in enumerate(lanes):
            if left_lane.orthogonality_metadata is None:
                invalid_pairs.append((left_lane.lane_id, left_lane.lane_id))
                continue
            for right_lane in lanes[index + 1 :]:
                if right_lane.orthogonality_metadata is None:
                    invalid_pairs.append((right_lane.lane_id, right_lane.lane_id))
                    continue
                if left_lane.orthogonality_metadata.distance_to(right_lane.orthogonality_metadata) < 3:
                    invalid_pairs.append((left_lane.lane_id, right_lane.lane_id))
        return invalid_pairs


class PortfolioSlotPolicy(BaseModel):
    slot_id: str
    mode: PortfolioSlotMode
    purpose: str
    active_candidate_id: str | None = None
    mutation_allowed: bool = False
    allowed_families: list[str] = Field(default_factory=list)
    codex_execution_mode: CodexExecutionMode = "disabled"
    worktree_name: str | None = None
    automation_name: str | None = None
    strategy_inheritance: str | None = None

    @model_validator(mode="after")
    def _validate_policy(self) -> PortfolioSlotPolicy:
        if self.mode == "active_candidate":
            if not self.mutation_allowed:
                raise ValueError("active_candidate slots must allow mutation.")
        if self.mode == "blank_slate_research":
            if not self.mutation_allowed:
                raise ValueError("blank_slate_research slots must allow mutation.")
            if self.strategy_inheritance != "none_from_prior_candidates":
                raise ValueError(
                    "blank_slate_research slots must explicitly declare strategy_inheritance = "
                    "'none_from_prior_candidates'."
                )
        return self


class PortfolioSettings(BaseModel):
    slots: list[PortfolioSlotPolicy] = Field(default_factory=list)

    def slot_by_id(self, slot_id: str) -> PortfolioSlotPolicy:
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        raise KeyError(f"Unknown portfolio slot: {slot_id}")


class AutonomyPolicySettings(BaseModel):
    active: bool = True
    queue_scope: Literal["policy_queue_only"] = "policy_queue_only"
    auto_approval_mode: Literal["machine_approvals"] = "machine_approvals"
    notify_boundary: Literal["ea_ready_or_blocked"] = "ea_ready_or_blocked"
    machine_approvable_stages: list[str] = Field(
        default_factory=lambda: ["mt5_packet", "mt5_parity_run", "mt5_validation"]
    )
    human_only_stages: list[str] = Field(default_factory=lambda: ["human_review"])
    blocked_stop_classes: list[str] = Field(
        default_factory=lambda: [
            "integrity_issue",
            "budget_exhausted",
            "policy_decision",
            "blocked_upstream_contract",
            "blocked_no_authorized_path",
        ]
    )
    max_cycles_per_manager_run: int = 8
    max_consecutive_blocked_runs: int = 1
    lease_ttl_seconds: int = 900
    watchdog_no_material_transition_cycles: int = 2
    watchdog_same_candidate_cycles: int = 2
    watchdog_same_blocked_reason_cycles: int = 2
    watchdog_repeated_insufficient_evidence_cycles: int = 2


class CodexOperatorPolicySettings(BaseModel):
    active: bool = True
    runtime: Literal["codex_app_repo_local"] = "codex_app_repo_local"
    planning_authority: Literal["codex"] = "codex"
    deterministic_kernel_authority: Literal["python_toml_control_plane"] = "python_toml_control_plane"
    default_governed_entrypoint: str = "run-governed-action"
    default_sandbox_mode: Literal["workspace-write", "read-only", "danger-full-access"] = "workspace-write"
    allow_openai_legacy_llm: bool = True
    allow_hooks_in_critical_path: bool = False
    hooks_windows_policy: Literal["disabled", "telemetry_only"] = "disabled"
    require_operator_manifest: bool = True
    capability_manifest_filename: str = "codex_capabilities.toml"
    capability_sync_timeout_seconds: int = 20
    capability_inventory_limit: int = 200
    capability_sample_bytes: int = 4000
    max_parallel_agents: int = 4
    max_agent_depth: int = 1
    repo_skill_source_dir: str = ".codex/skills-src"
    repo_skill_runtime_dir: str = ".agents/skills"
    repo_rules_file: str = ".codex/rules/default.rules"
    automation_specs_dir: str = "automations/specs"
    automation_prompts_dir: str = "automations/prompts"
    automation_default_execution: CodexAutomationExecution = "worktree"
    automation_default_status: CodexAutomationDefaultStatus = "paused"
    automation_manual_validation_required: bool = True
    hitl_boundaries: list[str] = Field(
        default_factory=lambda: [
            "manual_mt5_testing",
            "automation_activation",
            "external_manual_environment_step",
        ]
    )
    allowed_agent_roles: list[str] = Field(
        default_factory=lambda: [
            "portfolio_orchestrator",
            "lane_researcher",
            "governance_auditor",
            "throughput_worker",
            "validation_worker",
            "runtime_observer",
            "incident_reviewer",
        ]
    )


class MT5EnvironmentSettings(BaseModel):
    terminal_install_ids: list[str] = Field(default_factory=lambda: ["mt5_practice_01"])
    terminal_paths: list[str] = Field(default_factory=list)
    default_discovery_paths: list[str] = Field(
        default_factory=lambda: [
            r"C:\Program Files\OANDA MetaTrader 5 Terminal\terminal64.exe",
            r"C:\Program Files\MetaTrader 5\terminal64.exe",
        ]
    )
    portable_mode: bool = False
    report_root: str = "approvals/mt5_runs"
    tester_mode: str = "Every tick based on real ticks"
    parity_tester_mode: str | None = "1 minute OHLC"
    parity_diagnostic_tester_mode: str | None = "Every tick based on real ticks"
    allow_live_trading: bool = False
    shutdown_terminal: bool = True
    expert_relative_path: str = "Experts\\AgenticForex\\CandidateEA.ex5"
    compile_target_relative_path: str = "MQL5\\Experts\\AgenticForex\\CandidateEA.mq5"
    parity_launch_timeout_seconds: int = 900
    audit_file_mode: str = "common_files"
    audit_subdirectory: str = "AgenticForex\\Audit"
    stale_packet_policy: str = "logic_manifest_hash_or_missing_ex5"


class MLHardeningSettings(BaseModel):
    label_randomization_accuracy_ceiling: float = 0.55
    adversarial_auc_threshold: float = 0.55
    purged_cv_embargo_minimum_bars: int = 10
    feature_importance_top3_floor: float = 0.40
    model_persistence_format: str = "joblib"


class EvaOptimizerSettings(BaseModel):
    default_population_size: int = 30
    default_generations: int = 80
    fitness_pbo_penalty_weight: float = 0.3
    stop_loss_pips_bounds: list[float] = Field(default_factory=lambda: [5.0, 50.0])
    take_profit_pips_bounds: list[float] = Field(default_factory=lambda: [5.0, 100.0])
    signal_threshold_bounds: list[float] = Field(default_factory=lambda: [0.3, 0.9])
    holding_bars_bounds: list[float] = Field(default_factory=lambda: [5, 120])


class RegimeClassifierSettings(BaseModel):
    n_components_range: list[int] = Field(default_factory=lambda: [3, 5])
    regime_stability_min_window_agreement: float = 0.60


class MT5AlignmentSettings(BaseModel):
    feature_alignment_auc_threshold: float = 0.60


class SignalFilterSettings(BaseModel):
    model_type: str = "xgboost"
    max_leaves: int = 500


class GPRulesSettings(BaseModel):
    population_size: int = 150
    generations: int = 75
    max_tree_depth: int = 7
    parsimony_coefficient: float = 0.01
    crossover_probability: float = 0.7
    mutation_probability: float = 0.2
    tournament_size: int = 5
    min_signals_for_recommendation: int = 20
    min_pf_for_recommendation: float = 1.0


class MLVariancePilotSettings(BaseModel):
    """Phase 1.6.0 calibration outputs.

    Populated by ``scripts/run_ml_variance_pilot.py`` after the pilot
    report is committed. Every downstream ML phase gate must read
    ``effect_size_floor_pf`` and ``mde_pf`` from here — do not hardcode.
    """

    sigma_pf: float = 0.0
    mde_pf: float = 0.0
    effect_size_floor_pf: float = 0.0
    required_n_candidates: int = 0
    n_seeds: int = 10
    n_candidates: int = 3
    pilot_report_path: str | None = None
    pilot_id: str | None = None


class WorkflowSettings(BaseModel):
    discovery_workflow_id: str = "strategy_discovery_router_v1"
    review_workflow_id: str = "candidate_review_v1"


class PolicySettings(BaseModel):
    ftmo_ruleset_id: str = "ftmo_1step_2026_03"
    ftmo_timezone: str = "Europe/Prague"
    default_news_minimum_impact: str = "high"
    default_news_blackout_minutes_before: int = 15
    default_news_blackout_minutes_after: int = 15
    default_initial_balance: float = 100000.0
    default_account_currency: str = "USD"
    default_risk_per_trade_pct: float = 0.25
    default_leverage: float = 30.0
    default_contract_size: float = 100000.0
    default_pip_value_per_standard_lot: float = 10.0
    default_margin_buffer_pct: float = 10.0
    default_max_total_exposure_lots: float = 5.0


class Settings(BaseModel):
    project_root: Path
    llm: LLMSettings = Field(default_factory=LLMSettings)
    oanda: OandaSettings = Field(default_factory=OandaSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    validation: ValidationThresholds = Field(default_factory=ValidationThresholds)
    campaign: CampaignSettings = Field(default_factory=CampaignSettings)
    program: ProgramPolicySettings = Field(default_factory=ProgramPolicySettings)
    portfolio: PortfolioSettings = Field(default_factory=PortfolioSettings)
    autonomy: AutonomyPolicySettings = Field(default_factory=AutonomyPolicySettings)
    codex_operator: CodexOperatorPolicySettings = Field(default_factory=CodexOperatorPolicySettings)
    mt5_env: MT5EnvironmentSettings = Field(default_factory=MT5EnvironmentSettings)
    ml_hardening: MLHardeningSettings = Field(default_factory=MLHardeningSettings)
    eva_optimizer: EvaOptimizerSettings = Field(default_factory=EvaOptimizerSettings)
    regime_classifier: RegimeClassifierSettings = Field(default_factory=RegimeClassifierSettings)
    mt5_alignment: MT5AlignmentSettings = Field(default_factory=MT5AlignmentSettings)
    signal_filter: SignalFilterSettings = Field(default_factory=SignalFilterSettings)
    gp_rules: GPRulesSettings = Field(default_factory=GPRulesSettings)
    workflows: WorkflowSettings = Field(default_factory=WorkflowSettings)
    policy: PolicySettings = Field(default_factory=PolicySettings)
    ml_variance_pilot: MLVariancePilotSettings = Field(default_factory=MLVariancePilotSettings)

    def paths(self) -> ProjectPaths:
        return ProjectPaths.from_root(self.project_root)

    @property
    def catalog_path(self) -> Path:
        return self.paths().corpus_dir / self.data.catalog_filename

    @property
    def market_db_path(self) -> Path:
        return self.paths().state_dir / self.data.duckdb_filename

    @property
    def mt5_parity_db_path(self) -> Path:
        return self.paths().state_dir / self.data.mt5_parity_db_filename

    @property
    def economic_calendar_path(self) -> Path:
        return self.paths().state_dir / self.data.economic_calendar_filename


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(
    *,
    project_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Settings:
    import os

    paths = ProjectPaths.from_root(project_root)
    paths.ensure_directories()
    payload: dict = {"project_root": str(paths.root)}
    default_config_path = paths.config_dir / "default.toml"
    if default_config_path.exists():
        payload = _deep_merge(payload, tomllib.loads(default_config_path.read_text(encoding="utf-8")))
    for supplemental_name in (
        "data_contract.toml",
        "eval_gates.toml",
        "risk_policy.toml",
        "mt5_env.toml",
        "program_policy.toml",
        "portfolio_policy.toml",
        "autonomy_policy.toml",
        "codex_operator_policy.toml",
    ):
        supplemental_path = paths.config_dir / supplemental_name
        if supplemental_path.exists():
            payload = _deep_merge(payload, tomllib.loads(supplemental_path.read_text(encoding="utf-8")))
    # local.toml: user-specific overrides, gitignored
    local_config_path = paths.config_dir / "local.toml"
    if local_config_path.exists():
        payload = _deep_merge(payload, tomllib.loads(local_config_path.read_text(encoding="utf-8")))
    if config_path:
        config_file = Path(config_path)
        payload = _deep_merge(payload, tomllib.loads(config_file.read_text(encoding="utf-8")))
    # Environment variable overrides (highest priority)
    env_root = os.environ.get("GOBLIN_PROJECT_ROOT")
    if env_root:
        payload["project_root"] = env_root
    env_mt5 = os.environ.get("MT5_TERMINAL_PATH")
    if env_mt5:
        mt5_section = payload.setdefault("mt5_env", {})
        existing = mt5_section.get("terminal_paths", [])
        if env_mt5 not in existing:
            mt5_section["terminal_paths"] = [env_mt5] + existing
    settings = Settings.model_validate(payload)
    settings.paths().ensure_directories()
    return settings
