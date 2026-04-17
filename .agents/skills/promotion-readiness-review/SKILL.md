---
name: promotion-readiness-review
description: Review whether a candidate or lane is ready for the next governance stage using deterministic evidence. Use before parity packaging, human review, or lane retirement decisions.
---

# Promotion Readiness Review

Use deterministic reports, not narrative optimism.

## Workflow

1. Inspect `review_packet.json`, `robustness_report.json`, and any parity or forward artifacts.
2. Run `goblin validate-operator-contract --project-root <repo>` if operator assumptions are involved.
3. Summarize blocked evidence first, then any safe next step.

## Rules

- MT5 can explain failures but cannot establish research truth.
- Treat search-adjusted robustness and walk-forward stability as first-class gates.
- Preserve explicit HITL at manual testing or approval boundaries.
