# Incident Response

This runbook governs how to open, manage, and close Goblin incidents.
Severity and SLA requirements are defined in `Goblin/contracts/incident-severity-matrix.md`
and `Goblin/contracts/incident-sla.md`.

## Step 1 — Open the Incident

Call `open_incident_record` immediately when a material delta is detected.  Do not
wait for root cause before opening.

Required fields at open time:

- `candidate_id` — which candidate the incident applies to
- `title` — short description of the observed anomaly
- `severity` — S1/S2/S3/S4 per the classification table in `incident-severity-matrix.md`
- `sla_class` — `before_next_attach` for S1/S2; `before_next_promotion_gate` for S3
- `incident_type` — one of the typed incident classes in `incident-severity-matrix.md`
- `deployed_bundle_id` — the bundle active at the time of the incident (if known)
- `ladder_state_at_incident` — deployment ladder state at incident open

The incident register is at `Goblin/reports/incidents/<candidate_id>/`.

## Step 2 — Suspend If Required

| Severity | Suspension Rule |
| --- | --- |
| S1 | Halt new order placement immediately. No new live attach permitted. |
| S2 | Halt new order placement at end of current session. No new attach without accepted monitoring plan. |
| S3 | No suspension. Monitor and resolve before next promotion gate. |
| S4 | No action required. |

Call `list_open_blocking_incidents(settings, candidate_id=...)` to check whether
an attach is currently blocked.

## Step 3 — Freeze Artifacts

1. Freeze all reports and evidence from the run under investigation.
2. Confirm provenance for each relevant truth channel.
3. Do not allow any new runs to overwrite the frozen evidence paths.

## Step 4 — Validate Harness Trust

Before trusting any MT5 replay as evidence for root cause:

1. Confirm the replay certification status is `deployment_grade`.
2. Confirm baseline harness passed for the certification run.
3. Confirm tick provenance is `real_ticks` or `mixed` (not `generated_ticks`) if the
   incident involves timing or fill accuracy.

## Step 5 - Investigate

1. Compare the correct channel pairs with the correct comparison contract
   (`Goblin/contracts/comparison-matrix.md`).
2. Reference the statistical decision policy thresholds
   (`Goblin/contracts/statistical-decision-policy.md`) to determine whether the delta
   is within ordinary variance or a genuine anomaly.
3. Build or refresh the investigation pack from the frozen `incident_report.json`.
4. Confirm the pack contains scenario JSONs, a trace JSON, an evaluation suite, and a frozen benchmark-history snapshot.
5. Use the pack to preserve reproducible diagnosis; do not close the incident from narrative notes alone.
6. Keep the incident open until all unexplained deltas are attributed or reconciled.

## Step 6 — Close the Incident

Call `close_incident_record` with a closure packet that satisfies the severity requirements.

### S1 Closure Requirements

- `root_cause_classification`
- `root_cause_description`
- `corrective_action`
- `verification_evidence_path`
- `deployed_bundle_id`
- `approved_by`

### S2 Closure Requirements

- `root_cause_classification`
- `root_cause_description`
- `corrective_action` or `monitoring_plan` (at least one)
- `deployed_bundle_id`
- `approved_by`

### S3 Closure Requirements

- `root_cause_note`

### S4 Closure

Closed automatically after the observation window passes.  No formal closure required.

## Candidate Inheritance

If the affected candidate's validation stack is shared:

- Open S1 on source candidate → all inheritors blocked from new live attach.
- Open S2 on source candidate → inheritors must acknowledge shared risk before new attaches.

## Escalation

Severity may be escalated at any time with documented operator rationale.
Severity may not be downgraded without explicit operator decision and documented rationale.
