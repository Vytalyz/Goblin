from __future__ import annotations

import json

import pytest

from agentic_forex.goblin.controls import (
    enforce_ml_governance,
    write_model_registry_entry,
    write_offline_training_cycle,
    write_trusted_label_policy,
)
from agentic_forex.goblin.models import (
    ModelRegistryEntry,
    OfflineTrainingCycle,
    TrustedLabelPolicy,
)


def _base_policy(policy_id: str = "policy-1") -> TrustedLabelPolicy:
    return TrustedLabelPolicy(
        policy_id=policy_id,
        model_purpose="classification",
        provenance_requirements=["oanda_snapshot_only"],
        snapshot_freeze_rules=["labels_must_reference_frozen_snapshot"],
        ambiguity_rejection_criteria=["drop_if_label_confidence_below_threshold"],
        allowed_truth_channels=["research_backtest"],
        notes=["offline only"],
    )


def _base_cycle(model_id: str = "model-1", cycle_id: str = "cycle-1") -> OfflineTrainingCycle:
    return OfflineTrainingCycle(
        cycle_id=cycle_id,
        model_id=model_id,
        label_policy_id="policy-1",
        dataset_snapshot_id="snapshot-2026-03-31",
        holdout_window_ids=["window-a"],
        holdout_evaluation={"auc": 0.62},
        notes=["offline training cycle"],
    )


def test_write_trusted_label_policy_persists_artifact(settings):
    policy = write_trusted_label_policy(settings, policy=_base_policy())

    assert policy.report_path is not None
    assert policy.report_path.exists()
    payload = json.loads(policy.report_path.read_text(encoding="utf-8"))
    assert payload["policy_id"] == "policy-1"


def test_write_offline_training_cycle_requires_holdout_windows(settings):
    cycle = _base_cycle()
    cycle.holdout_window_ids = []

    with pytest.raises(ValueError, match="offline_training_requires_holdout_windows"):
        write_offline_training_cycle(settings, cycle=cycle)


def test_write_offline_training_cycle_requires_mt5_cert_for_live_execution(settings):
    cycle = _base_cycle()
    cycle.touches_live_execution = True
    cycle.mt5_certification_path = None

    with pytest.raises(ValueError, match="live_execution_model_requires_mt5_certification"):
        write_offline_training_cycle(settings, cycle=cycle)


def test_enforce_ml_governance_blocks_online_self_tuning(settings):
    write_model_registry_entry(
        settings,
        entry=ModelRegistryEntry(
            model_id="model-self-tune",
            purpose="classification",
            training_dataset_snapshot="snapshot-1",
            label_policy="policy-1",
            approval_state="approved",
            online_self_tuning_enabled=True,
        ),
    )

    with pytest.raises(ValueError, match="ml_governance_blocked_online_self_tuning"):
        enforce_ml_governance(settings, model_id="model-self-tune")


def test_enforce_ml_governance_blocks_unapproved_live_model(settings):
    write_model_registry_entry(
        settings,
        entry=ModelRegistryEntry(
            model_id="model-unapproved",
            purpose="classification",
            training_dataset_snapshot="snapshot-1",
            label_policy="policy-1",
            approval_state="pending",
            online_self_tuning_enabled=False,
        ),
    )

    with pytest.raises(ValueError, match="ml_governance_blocked_unapproved_model"):
        enforce_ml_governance(settings, model_id="model-unapproved", touches_live_execution=True)


def test_model_registry_entry_links_label_policy_and_training_cycle(settings):
    policy = write_trusted_label_policy(settings, policy=_base_policy(policy_id="policy-linked"))
    cycle = write_offline_training_cycle(settings, cycle=_base_cycle(model_id="model-linked", cycle_id="cycle-linked"))

    entry = write_model_registry_entry(
        settings,
        entry=ModelRegistryEntry(
            model_id="model-linked",
            purpose="classification",
            training_dataset_snapshot="snapshot-1",
            label_policy="policy-linked",
            approval_state="approved",
        ),
    )

    assert entry.label_policy_path is not None
    assert entry.training_cycle_path is not None
    assert entry.label_policy_path == policy.report_path
    assert entry.training_cycle_path == cycle.report_path
