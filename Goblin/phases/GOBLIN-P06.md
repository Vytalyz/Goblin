# GOBLIN-P06: Incident And Safety Envelope System

## Objective

Turn failures into governed incidents instead of narrative debates, with severity-driven suspension rules and SLA obligations tied to operational events rather than wall-clock time.

## Dependencies

- `GOBLIN-P05`

## Inputs

- `Goblin/contracts/statistical-decision-policy.md` (authored in P05 enrichment)
- `Goblin/contracts/deployment-ladder.md` (authored in P07; P06 consumes ladder state for incident closure packets)
- `Goblin/contracts/deployment-bundle.md` (authored in P07; P06 incident closure packets require bundle identity)

Note: P07 depends on P05 only and may be authored in parallel with P06. P06 closure enforcement requires P07 outputs, but P06 can be started and the severity/SLA contracts authored before P07 completes.

## Build Scope

- Define the incident severity matrix: S1–S4 levels, incident type classification, automatic suspension rules, and candidate inheritance rules.
- Define incident SLAs as operational-event-relative deadlines (before-next-attach, before-promotion-gate), not wall-clock times.
- Update the incident response runbook to reference severity levels and required closure evidence by severity.
- Integrate statistical decision policy thresholds into incident open/close triggers.
- Specify how related candidates inherit safety blocks when they depend on an untrusted validation stack.

## Outputs

- incident severity matrix
- incident SLA contract
- updated incident response runbook

## Expected Artifacts

- `Goblin/contracts/incident-severity-matrix.md`
- `Goblin/contracts/incident-sla.md`
- `Goblin/runbooks/INCIDENT_RESPONSE.md`

## Checkpoint Targets

- Severity matrix classifies all incident types with default severity and escalation rules.
- SLA contract uses operational-event-relative deadlines with required closure evidence per severity.
- Incident response runbook references severity matrix and SLA contract.
- `IncidentRecord` model carries severity and SLA class fields.

## Authoritative Artifacts

- `Goblin/contracts/incident-severity-matrix.md`
- `Goblin/contracts/incident-sla.md`
- `Goblin/runbooks/INCIDENT_RESPONSE.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P06.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P06 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Any unexplained material delta opens or keeps open an incident.
- Incident severity drives suspension and closure evidence requirements, not operator discretion.
- `IncidentRecord` carries severity and SLA class.
