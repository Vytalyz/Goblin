# GOBLIN-P10: Portfolio And Candidate Strategy Program

## Objective

Resume and improve strategy search under repaired governance, with promotion decisions anchored to the statistical decision policy and deployment ladder rather than narrative judgment.

## Dependencies

- `GOBLIN-P09`

## Inputs

- `Goblin/contracts/statistical-decision-policy.md`
- `Goblin/contracts/deployment-ladder.md`
- `Goblin/contracts/execution-cost-contract.md`
- `Goblin/contracts/experiment-accounting.md`

## Build Scope

- Resume governed strategy search only after truth-stack, incident controls, and experiment governance are in place.
- Separate alpha quality from deployment fit through candidate scorecards, deployment profiles, and risk overlays.
- Enforce that promotion packets reference statistical decision policy keys, not free-text judgment.
- Enforce that promotion packets reference the candidate's current deployment ladder state; a candidate below `observed_demo` cannot receive a promotion decision.
- Enforce benchmark/challenger rules and promotion packets across overlap and gap lanes.
- Ensure improvement claims cannot hide deployment-fit changes inside alpha claims.

## Outputs

- candidate scorecard
- deployment profile
- promotion decision packet

## Expected Artifacts

- `Goblin/contracts/candidate-scorecard.md`
- `Goblin/contracts/promotion-decision-packet.md`

## Checkpoint Targets

- Promotion decision packet cites statistical policy keys for every promotion criterion.
- Promotion decision packet cites the candidate's deployment ladder state.
- Promotion is blocked for candidates below `observed_demo` ladder state.
- Deployment-fit changes that cross declared thresholds require a new bundle.

## Authoritative Artifacts

- `Goblin/contracts/candidate-scorecard.md`
- `Goblin/contracts/promotion-decision-packet.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P10.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P10 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- No improvement claim can hide deployment changes inside alpha claims.
- Promotion criteria reference statistical policy thresholds, not free-text judgment.
- Deployment ladder state is required in every promotion decision packet.
