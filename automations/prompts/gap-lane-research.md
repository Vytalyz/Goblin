# Gap Lane Research

Use $governed-strategy-search, $promotion-readiness-review, and $parity-packaging when needed.

Inspect the latest operator state and queue snapshot, then choose the single next governed action with the highest expected research value for the mutable non-overlap slot.

Default target slot:
- `gap_blank_slate`

Preferred execution path:
- run `goblin export-operator-state --project-root <repo>`
- run `goblin queue-snapshot --project-root <repo>`
- run the cached scan for the blank-slate lane and apply the book-prior hypothesis screen before any new materialization
- materialize only top eligible open-anchor families: `europe_open_impulse_retest_research`, `europe_open_opening_range_retest_research`, and `europe_open_early_follow_through_research`
- compare only the eligible candidates, then run the anchored phase/density audit
- if the audit returns `refine_family_once`, allow one bounded refinement; otherwise stop and report the adjustment boundary
- only route to throughput, promotion-readiness review, and parity packaging after a candidate clears the book-guided front door and the phase/density audit

Rules:
- Never mutate AF-CAND-0263.
- Stay blank-slate on the gap lane.
- Treat the Codex layer as the planner and the Python/TOML kernel as the authoritative governed executor.
- Treat Chan-style book claims as priors and vetoes only; they may reject or penalize a family, but never approve one by themselves.
- Do not route the active slot back into reclaim, balance-breakout, release-persistence, or other retired exploratory branches unless policy is changed explicitly.
- Stop on approval, HITL, or integrity boundaries and report exact artifact paths.
