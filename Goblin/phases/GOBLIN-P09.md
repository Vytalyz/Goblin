# GOBLIN-P09: Strategy Methodology, Search-Bias, And Experiment Governance

## Objective

Improve strategy quality without repeating the same research-control mistakes, by making experiment accounting binding rather than documentary and adding per-family budget caps that enforce search discipline.

## Dependencies

- `GOBLIN-P08`

## Inputs

- `Goblin/contracts/statistical-decision-policy.md`
- `Goblin/contracts/execution-cost-contract.md`

## Build Scope

- Translate the strategy book into a methodology rubric rather than a trading oracle.
- Add strategy rationale cards and search-bias controls at the family level.
- Add experiment budgeting: declare per-family budget caps (maximum candidates evaluated, maximum mutation depth, maximum failed refinement attempts before suspension), not as aspirational limits but as enforced gates.
- Define invalid comparison rules: prohibit in-sample vs out-of-sample comparisons, prohibit comparing across different date windows without regime accounting, prohibit treating research backtests and MT5 replay as answering the same question.
- Define suspension thresholds after failed refinements: if a family has exhausted its refinement budget without a viable candidate, the family must be suspended rather than infinitely iterated.
- Use statistical decision policy thresholds as the research floor — research metrics must exceed the same floors that live evidence must meet.

## Outputs

- methodology rubric
- strategy rationale cards contract
- experiment accounting ledger (with budget enforcement)

## Expected Artifacts

- `Goblin/contracts/strategy-rationale-card.md`
- `Goblin/contracts/experiment-accounting.md`

## Checkpoint Targets

- Experiment-accounting contract captures per-family budget, mutation depth, invalid comparison rules, and suspension thresholds after failed refinements.
- Strategy rationale card contract requires thesis, invalidation conditions, hostile regimes, and execution assumptions.
- Both contracts reference the statistical decision policy as the shared research floor.

## Authoritative Artifacts

- `Goblin/contracts/strategy-rationale-card.md`
- `Goblin/contracts/experiment-accounting.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P09.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P09 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- No live/demo candidate exists without a rationale card and experiment lineage.
- Experiment accounting captures the budget consumed and whether suspension thresholds were hit.
- Budget caps start permissive but are documented and enforced; they may be tightened as evidence accumulates.
