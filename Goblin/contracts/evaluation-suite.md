# Evaluation Suite

The Goblin evaluation layer measures reliability and repeatability of investigations, validations, and comparison workflows.

## Canonical Outputs

- one evaluation suite per reproducible investigation pack
- a frozen benchmark history snapshot for the same incident
- scenario ids that separate deterministic regression, MT5 replay-backed, and live/runtime reconciliation checks

## Core Scenario Types

- deterministic regression scenarios
- MT5 replay-backed scenarios
- live/runtime incident scenarios
- multi-iteration reliability runs
- benchmark history snapshots

## Rules

- Evaluation suites are built from frozen incident reports and remain advisory to the runtime path.
- Deterministic replay scenarios and MT5 replay-backed scenarios must stay distinct inside the suite.
- Benchmark history is frozen with the incident report hash so reruns can prove they used the same evidence base.
- Suites may summarize repeatability and reliability, but they do not replace incident severity, SLA, or release controls.
