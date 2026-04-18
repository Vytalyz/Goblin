from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def discover_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(slots=True, frozen=True)
class ProjectPaths:
    root: Path

    @classmethod
    def from_root(cls, root: str | Path | None = None) -> ProjectPaths:
        resolved_root = Path(root).resolve() if root else discover_project_root()
        return cls(root=resolved_root)

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def codex_dir(self) -> Path:
        return self.root / ".codex"

    @property
    def codex_agents_dir(self) -> Path:
        return self.codex_dir / "agents"

    @property
    def codex_skills_src_dir(self) -> Path:
        return self.codex_dir / "skills-src"

    @property
    def codex_rules_dir(self) -> Path:
        return self.codex_dir / "rules"

    @property
    def repo_agents_dir(self) -> Path:
        return self.root / ".agents"

    @property
    def repo_agent_skills_dir(self) -> Path:
        return self.repo_agents_dir / "skills"

    @property
    def repo_agent_plugins_dir(self) -> Path:
        return self.repo_agents_dir / "plugins"

    @property
    def workflows_dir(self) -> Path:
        return self.root / "workflows"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def roles_dir(self) -> Path:
        return self.root / "agents" / "roles"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def capability_pages_dir(self) -> Path:
        return self.knowledge_dir / "codex_capability_pages"

    @property
    def traces_dir(self) -> Path:
        return self.root / "traces"

    @property
    def codex_operator_traces_dir(self) -> Path:
        return self.traces_dir / "codex_operator"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def operator_reports_dir(self) -> Path:
        return self.reports_dir / "operator"

    @property
    def published_dir(self) -> Path:
        return self.root / "published"

    @property
    def approvals_dir(self) -> Path:
        return self.root / "approvals"

    @property
    def mt5_runs_dir(self) -> Path:
        return self.approvals_dir / "mt5_runs"

    @property
    def experiments_dir(self) -> Path:
        return self.root / "experiments"

    @property
    def automations_dir(self) -> Path:
        return self.root / "automations"

    @property
    def automation_specs_dir(self) -> Path:
        return self.automations_dir / "specs"

    @property
    def automation_prompts_dir(self) -> Path:
        return self.automations_dir / "prompts"

    @property
    def goblin_dir(self) -> Path:
        return self.root / "Goblin"

    @property
    def goblin_phases_dir(self) -> Path:
        return self.goblin_dir / "phases"

    @property
    def goblin_state_dir(self) -> Path:
        return self.goblin_dir / "state"

    @property
    def goblin_phase_state_dir(self) -> Path:
        return self.goblin_state_dir / "phases"

    @property
    def goblin_artifact_state_dir(self) -> Path:
        return self.goblin_state_dir / "artifacts"

    @property
    def goblin_artifact_indexes_dir(self) -> Path:
        return self.goblin_artifact_state_dir / "indexes"

    @property
    def goblin_checkpoints_dir(self) -> Path:
        return self.goblin_dir / "checkpoints"

    @property
    def goblin_decisions_dir(self) -> Path:
        return self.goblin_dir / "decisions"

    @property
    def goblin_reports_dir(self) -> Path:
        return self.goblin_dir / "reports"

    @property
    def goblin_research_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "research_backtest"

    @property
    def goblin_mt5_replay_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "mt5_replay"

    @property
    def goblin_live_demo_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "live_demo"

    @property
    def goblin_broker_history_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "broker_account_history"

    @property
    def goblin_truth_alignment_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "truth_alignment"

    @property
    def goblin_incident_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "incidents"

    @property
    def goblin_investigation_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "investigations"

    @property
    def goblin_evaluation_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "evaluation_suites"

    @property
    def goblin_benchmark_history_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "benchmark_history"

    @property
    def goblin_mt5_certification_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "mt5_certification"

    @property
    def goblin_deployment_bundles_dir(self) -> Path:
        return self.goblin_reports_dir / "deployment_bundles"

    @property
    def goblin_rationale_cards_dir(self) -> Path:
        return self.goblin_reports_dir / "strategy_rationale_cards"

    @property
    def goblin_experiment_accounting_dir(self) -> Path:
        return self.goblin_reports_dir / "experiment_accounting"

    @property
    def goblin_methodology_audits_dir(self) -> Path:
        return self.goblin_reports_dir / "strategy_methodology_audits"

    @property
    def goblin_scorecards_dir(self) -> Path:
        return self.goblin_reports_dir / "candidate_scorecards"

    @property
    def goblin_model_registry_dir(self) -> Path:
        return self.goblin_reports_dir / "model_registry"

    @property
    def goblin_knowledge_reports_dir(self) -> Path:
        return self.goblin_reports_dir / "knowledge"

    @property
    def goblin_knowledge_events_dir(self) -> Path:
        return self.goblin_knowledge_reports_dir / "events"

    @property
    def goblin_retrieval_documents_dir(self) -> Path:
        return self.goblin_knowledge_reports_dir / "retrieval_documents"

    @property
    def goblin_vector_memory_dir(self) -> Path:
        return self.goblin_knowledge_reports_dir / "vector_memory"

    @property
    def goblin_agent_roles_dir(self) -> Path:
        return self.goblin_knowledge_reports_dir / "agent_roles"

    @property
    def goblin_retrieval_queries_dir(self) -> Path:
        return self.goblin_knowledge_reports_dir / "retrieval_queries"

    @property
    def goblin_label_policies_dir(self) -> Path:
        return self.goblin_reports_dir / "label_policies"

    @property
    def goblin_training_cycles_dir(self) -> Path:
        return self.goblin_reports_dir / "training_cycles"

    @property
    def goblin_run_records_dir(self) -> Path:
        return self.goblin_reports_dir / "run_records"

    @property
    def goblin_templates_dir(self) -> Path:
        return self.goblin_dir / "templates"

    @property
    def goblin_runbooks_dir(self) -> Path:
        return self.goblin_dir / "runbooks"

    @property
    def goblin_contracts_dir(self) -> Path:
        return self.goblin_dir / "contracts"

    @property
    def goblin_program_status_path(self) -> Path:
        return self.goblin_state_dir / "program_status.json"

    @property
    def campaigns_dir(self) -> Path:
        return self.experiments_dir / "campaigns"

    @property
    def governed_loops_dir(self) -> Path:
        return self.experiments_dir / "governed_loops"

    @property
    def program_loops_dir(self) -> Path:
        return self.experiments_dir / "program_loops"

    @property
    def autonomous_manager_dir(self) -> Path:
        return self.experiments_dir / "autonomous_manager"

    @property
    def events_path(self) -> Path:
        return self.experiments_dir / "events.jsonl"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def corpus_dir(self) -> Path:
        return self.data_dir / "corpus"

    @property
    def corpus_extracted_dir(self) -> Path:
        return self.corpus_dir / "extracted"

    @property
    def corpus_quality_dir(self) -> Path:
        return self.corpus_dir / "quality"

    @property
    def corpus_notes_dir(self) -> Path:
        return self.corpus_dir / "knowledge_notes"

    @property
    def corpus_claims_dir(self) -> Path:
        return self.corpus_dir / "claims"

    @property
    def corpus_contradictions_dir(self) -> Path:
        return self.corpus_dir / "contradictions"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def raw_csv_dir(self) -> Path:
        return self.raw_dir / "csv_adapter"

    @property
    def raw_oanda_dir(self) -> Path:
        return self.raw_dir / "oanda"

    @property
    def raw_oanda_backfill_dir(self) -> Path:
        return self.raw_oanda_dir / "backfill"

    @property
    def raw_calendar_dir(self) -> Path:
        return self.raw_dir / "economic_calendar"

    @property
    def raw_mt5_dir(self) -> Path:
        return self.raw_dir / "mt5_parity"

    @property
    def normalized_dir(self) -> Path:
        return self.data_dir / "normalized"

    @property
    def normalized_research_dir(self) -> Path:
        return self.normalized_dir / "research"

    @property
    def normalized_mt5_dir(self) -> Path:
        return self.normalized_dir / "mt5_parity"

    @property
    def features_dir(self) -> Path:
        return self.data_dir / "features"

    @property
    def labels_dir(self) -> Path:
        return self.data_dir / "labels"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"

    @property
    def leases_dir(self) -> Path:
        return self.state_dir / "leases"

    @property
    def idempotency_dir(self) -> Path:
        return self.state_dir / "idempotency"

    @property
    def incidents_dir(self) -> Path:
        return self.state_dir / "incidents"

    @property
    def market_quality_reports_dir(self) -> Path:
        return self.reports_dir / "market_data_quality"

    @property
    def policy_reports_dir(self) -> Path:
        return self.reports_dir / "policy"

    @property
    def portfolio_reports_dir(self) -> Path:
        return self.reports_dir / "portfolio"

    @property
    def observational_knowledge_dir(self) -> Path:
        return self.knowledge_dir / "observational"

    @property
    def capability_catalog_path(self) -> Path:
        return self.knowledge_dir / "codex_capability_catalog.json"

    @property
    def capability_index_path(self) -> Path:
        return self.knowledge_dir / "codex_capability_index.md"

    def ensure_directories(self) -> None:
        for path in (
            self.config_dir,
            self.codex_dir,
            self.codex_agents_dir,
            self.codex_skills_src_dir,
            self.codex_rules_dir,
            self.repo_agents_dir,
            self.repo_agent_skills_dir,
            self.repo_agent_plugins_dir,
            self.workflows_dir,
            self.prompts_dir,
            self.roles_dir,
            self.skills_dir,
            self.knowledge_dir,
            self.capability_pages_dir,
            self.traces_dir,
            self.codex_operator_traces_dir,
            self.reports_dir,
            self.operator_reports_dir,
            self.published_dir,
            self.approvals_dir,
            self.mt5_runs_dir,
            self.experiments_dir,
            self.automations_dir,
            self.automation_specs_dir,
            self.automation_prompts_dir,
            self.goblin_dir,
            self.goblin_phases_dir,
            self.goblin_state_dir,
            self.goblin_phase_state_dir,
            self.goblin_artifact_state_dir,
            self.goblin_artifact_indexes_dir,
            self.goblin_checkpoints_dir,
            self.goblin_decisions_dir,
            self.goblin_reports_dir,
            self.goblin_research_reports_dir,
            self.goblin_mt5_replay_reports_dir,
            self.goblin_live_demo_reports_dir,
            self.goblin_broker_history_reports_dir,
            self.goblin_truth_alignment_reports_dir,
            self.goblin_incident_reports_dir,
            self.goblin_investigation_reports_dir,
            self.goblin_evaluation_reports_dir,
            self.goblin_benchmark_history_reports_dir,
            self.goblin_mt5_certification_reports_dir,
            self.goblin_deployment_bundles_dir,
            self.goblin_rationale_cards_dir,
            self.goblin_scorecards_dir,
            self.goblin_model_registry_dir,
            self.goblin_knowledge_reports_dir,
            self.goblin_knowledge_events_dir,
            self.goblin_retrieval_documents_dir,
            self.goblin_vector_memory_dir,
            self.goblin_agent_roles_dir,
            self.goblin_retrieval_queries_dir,
            self.goblin_label_policies_dir,
            self.goblin_training_cycles_dir,
            self.goblin_templates_dir,
            self.goblin_runbooks_dir,
            self.goblin_contracts_dir,
            self.campaigns_dir,
            self.governed_loops_dir,
            self.program_loops_dir,
            self.autonomous_manager_dir,
            self.corpus_dir,
            self.corpus_extracted_dir,
            self.corpus_quality_dir,
            self.corpus_notes_dir,
            self.corpus_claims_dir,
            self.corpus_contradictions_dir,
            self.raw_dir,
            self.raw_csv_dir,
            self.raw_oanda_dir,
            self.raw_oanda_backfill_dir,
            self.raw_calendar_dir,
            self.raw_mt5_dir,
            self.normalized_dir,
            self.normalized_research_dir,
            self.normalized_mt5_dir,
            self.features_dir,
            self.labels_dir,
            self.state_dir,
            self.leases_dir,
            self.idempotency_dir,
            self.incidents_dir,
            self.market_quality_reports_dir,
            self.policy_reports_dir,
            self.portfolio_reports_dir,
            self.observational_knowledge_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
