---
name: parity-packaging
description: Package a candidate for MT5 parity or practice validation without treating MT5 as research truth. Use after governed throughput or parity-gated readiness steps.
---

# Parity Packaging

Route through deterministic parity commands only.

## Workflow

1. Confirm parity readiness from review and robustness artifacts.
2. Use `goblin run-governed-action --action next_step ...` or the dedicated MT5 packet/validation commands if already approval-cleared.
3. Record and inspect the resulting packet or validation reports.

## Rules

- Keep MT5 practice-only.
- Do not infer promotion truth from MT5 parity outputs alone.
- Stop immediately if approvals are stale or missing.
