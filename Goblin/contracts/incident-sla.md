# Incident SLA

This contract defines response and closure obligations for Goblin incidents. SLAs are expressed as operational-event-relative deadlines, not wall-clock times, because this system is operated by a small team and clock-time SLAs are not enforceable in practice.

## SLA Framing Principle

An SLA of "before next attach" means the incident must be resolved before the EA can be attached again after the triggering event. An SLA of "before next promotion gate" means the incident must be resolved before the candidate is evaluated for any promotion decision. These deadlines are tied to operational events, not to calendar time.

## Response Obligations By Severity

| Severity | First Response Deadline | Resolution Deadline | Escalation If Missed |
| --- | --- | --- | --- |
| `S1` | Before any new order placement | Before next live attach attempt | Cannot proceed to any new attach without operator override and documented rationale |
| `S2` | Before end of current trading session | Before next live attach attempt | New attach requires acknowledged monitoring plan; promotion gate is blocked |
| `S3` | Before next promotion gate evaluation | Before live evidence from the affected run is cited in any decision | Promotion gate blocked; monitoring may continue |
| `S4` | No response required | Observation window closes automatically | No escalation |

## Required Fields In Closure Packet By Severity

Closure packets for `S1` and `S2` incidents must include the following fields. Missing required fields block closure.

### S1 Closure Packet Required Fields

- `incident_id`
- `root_cause_classification`: one of the incident types in `incident-severity-matrix.md`
- `root_cause_description`: human-readable explanation
- `corrective_action`: description of what was changed or fixed
- `verification_evidence_path`: path to verification replay, re-run, or broker reconciliation result
- `deployed_bundle_id`: bundle identity of the EA that was running when the incident occurred (see `deployment-bundle.md`)
- `ladder_state_at_incident`: deployment ladder state at incident open
- `approved_by`: operator name or identifier
- `closure_utc`

### S2 Closure Packet Required Fields

- `incident_id`
- `root_cause_classification`
- `root_cause_description`
- `corrective_action` or `monitoring_plan` (at least one required)
- `deployed_bundle_id`
- `approved_by`
- `closure_utc`

### S3 Closure Packet Required Fields

- `incident_id`
- `root_cause_note`: brief note
- `closure_utc`

## Incident Re-Open Rules

An incident that has been closed may be re-opened if:
- New evidence emerges that contradicts the accepted root cause.
- The same incident type recurs within three live sessions after closure.
- A verification replay cited in the closure packet is later found to be non-representative.

Re-opened incidents inherit the original severity unless escalated by the operator.

## Monitoring Status

An incident in `monitoring` status means the root cause is known and accepted but the resolution has not been verified. Monitoring incidents:
- Do not block new attaches for `S3`.
- Block new attaches for `S2` unless a formal monitoring plan with defined triggers is accepted.
- Always block new attaches for `S1` — `S1` incidents cannot remain in monitoring; they must be resolved.

## Incident Register

All open and recently closed incidents must be trackable via the Goblin incident register. The register must be readable without executing code. The current state is in `Goblin/reports/incidents/` with one JSON file per incident.
