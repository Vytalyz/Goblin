from __future__ import annotations

from datetime import UTC, datetime

from agentic_forex.config import Settings
from agentic_forex.experiments.iteration import iterate_scalping_target
from agentic_forex.goblin.controls import enforce_strategy_governance
from agentic_forex.governance.models import CampaignSpec, CampaignState
from agentic_forex.governance.trial_ledger import append_failure_record, append_trial_entry
from agentic_forex.utils.io import read_json, write_json


def run_bounded_campaign(spec: CampaignSpec, settings: Settings) -> CampaignState:
    enforce_strategy_governance(settings, family=spec.family)
    state = load_or_create_campaign_state(spec, settings)
    state.status = "running"
    state.state_version += 1
    state.updated_utc = _utc_now()
    write_json(state.state_path, state.model_dump(mode="json"))
    try:
        for target_id in spec.target_candidate_ids:
            if state.iterations_run >= spec.max_iterations:
                state.status = "stopped"
                state.stop_reason = "max_iterations_reached"
                break
            if state.trials_consumed >= spec.trial_cap_per_family:
                state.status = "stopped"
                state.stop_reason = "trial_cap_reached"
                append_failure_record(
                    settings,
                    candidate_id=target_id,
                    stage="campaign_controller",
                    failure_code="campaign_budget_exhausted",
                    details={"campaign_id": spec.campaign_id},
                    campaign_id=spec.campaign_id,
                )
                break
            report = iterate_scalping_target(
                settings,
                baseline_candidate_id=spec.baseline_candidate_id,
                target_candidate_id=target_id,
            )
            state.iterations_run += 1
            state.trials_consumed += len(report.variants)
            state.active_candidate_ids = [variant.candidate_id for variant in report.variants]
            if report.recommended_candidate_id and report.recommended_candidate_id not in state.promoted_candidate_ids:
                state.promoted_candidate_ids.append(report.recommended_candidate_id)
            append_trial_entry(
                settings,
                candidate_id=report.recommended_candidate_id or target_id,
                family=spec.family,
                stage="campaign_iteration",
                campaign_id=spec.campaign_id,
                parent_candidate_ids=[spec.baseline_candidate_id, target_id],
                mutation_policy="bounded_iteration",
                artifact_paths={
                    "campaign_state_path": str(state.state_path),
                    "iteration_report_path": str(report.report_path),
                    "comparison_report_path": str(report.comparison_report_path),
                },
                gate_outcomes={"recommended_candidate_id": report.recommended_candidate_id},
            )
            if spec.stop_on_review_eligible_provisional and any(
                variant.trade_count >= settings.validation.minimum_test_trade_count for variant in report.variants
            ):
                state.status = "completed"
                state.stop_reason = "review_eligible_provisional_candidate_found"
                break
        else:
            state.status = "completed"
            state.stop_reason = "targets_exhausted"
    finally:
        state.state_version += 1
        state.updated_utc = _utc_now()
        write_json(state.state_path, state.model_dump(mode="json"))
    return state


def load_or_create_campaign_state(spec: CampaignSpec, settings: Settings) -> CampaignState:
    state_path = settings.paths().campaigns_dir / spec.campaign_id / "state.json"
    spec_path = state_path.parent / "spec.json"
    if not spec_path.exists():
        write_json(spec_path, spec.model_dump(mode="json"))
    if state_path.exists():
        return CampaignState.model_validate(read_json(state_path))
    state = CampaignState(
        campaign_id=spec.campaign_id,
        family=spec.family,
        baseline_candidate_id=spec.baseline_candidate_id,
        parent_campaign_id=spec.parent_campaign_id,
        current_step_type=spec.step_type,
        active_candidate_ids=list(spec.target_candidate_ids),
        state_path=state_path,
    )
    write_json(state.state_path, state.model_dump(mode="json"))
    return state


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
