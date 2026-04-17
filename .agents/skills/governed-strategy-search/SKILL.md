---
name: governed-strategy-search
description: Run Codex-led strategy search through the deterministic kernel without bypassing governance. Use when exploring queues, launching governed actions, or routing portfolio work.
---

# Governed Strategy Search

Use repo-native governed actions and queue/state exports as the control surface.

## Workflow

1. Run `goblin export-operator-state --project-root <repo>`.
2. Run `goblin queue-snapshot --project-root <repo>`.
3. Execute the next bounded action with `goblin run-governed-action ...`.
4. Inspect the resulting operator manifest before chaining the next step.

## Rules

- Never bypass approvals, parity class, provenance, or trial ledgers.
- Never mutate `AF-CAND-0263`.
- Keep blank-slate gap work independent from `AF-CAND-0263` strategy logic.
