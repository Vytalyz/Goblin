# Model Registry

Goblin ML is offline, governed, and approval-gated.

## Required Registry Fields

- training dataset snapshot
- label policy
- label policy artifact path
- feature schema
- evaluation windows
- calibration results
- drift thresholds
- offline training cycle artifact path
- approval state
- online self-tuning enabled flag (must be `false`)

## Required Label Policy Controls

- trusted label policy must define ambiguity rejection criteria
- trusted label policy must enumerate allowed truth channels
- trusted label policy must be written under `Goblin/reports/label_policies/<policy_id>/trusted_label_policy.json`

## Required Offline Training Controls

- each offline training cycle must include holdout windows
- any cycle that touches live execution must include MT5 certification evidence
- training cycle artifacts must be written under
	`Goblin/reports/training_cycles/<model_id>/<cycle_id>/offline_training_cycle.json`

## Runtime Governance Enforcement

- model registry entries with `online_self_tuning_enabled=true` are blocked
- models touching live execution must have `approval_state=approved`

## Prohibitions

- live online self-tuning
- autonomous model promotion
- using ambiguous labels as training truth
