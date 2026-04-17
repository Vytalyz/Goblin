# Goblin Repository Rules

These instructions apply to the repository root unless a deeper `AGENTS.md` overrides them.

## Durable System Rules

- Keep the Python/TOML control plane authoritative.
- `OANDA` is the canonical research data source.
- `MT5` is practice/parity only and must never become research truth.
- `Goblin` is the umbrella program identity rooted at `/Goblin`.
- Governed `MT5` demo-account EA automation is allowed for live-demo observability, broker reconciliation, and deployment-ladder evidence collection.
- Real-money automated trading is forbidden unless a later explicit governance change authorizes it.
- No stage may bypass provenance, approval, parity-class, or trial-ledger controls.
- Governed incident, promotion, and review paths must prefer explicit artifact references or channel-owned Goblin indexes over heuristic artifact discovery.

## Bare Vs Codex

- The bare system is the repo-native workflow:
  - program loop
  - autonomous manager
  - approvals
  - parity and forward artifacts
  - audit ledger
- Goblin is the umbrella control plane over the existing runtime kernel.
- Keep `src/agentic_forex` as the deterministic kernel until a later explicit migration.
- Codex is an outer operator/orchestration layer only.
- Do not introduce a runtime dependency on `OPENAI_API_KEY` or a permanently open Codex session.
- Preserve the existing internal workflow-engine assets under `agents/roles/`, `workflows/`, and `skills/`.
- Keep Codex-native assets under `.codex/` separate from the internal workflow-engine assets.

## Active Portfolio Slots

- `overlap_benchmark`
  - locked benchmark candidate: `AF-CAND-0263`
  - purpose: demo monitoring reference
  - mutation is forbidden
- `gap_blank_slate`
  - purpose: next non-overlap deployable strategy
  - strategy logic must start blank-slate
  - do not borrow thresholds, geometry, or holding logic from `AF-CAND-0263`

## Portfolio Controls

- Slot policy is authoritative for whether a lane is mutable, benchmark-only, or parity-eligible.
- `AF-CAND-0263` must never be mutated through portfolio routing.
- New strategy families must remain governed by explicit parity-class assignment before official parity.
- Diagnostic MT5 evidence may explain failures but cannot establish promotion truth.
- Governed MT5 demo runs must produce the live-demo contract artifacts and remain subordinate to broker/account reconciliation and deployment-ladder state.
- No candidate rescue is allowed through the new gap lane.

## Codex Execution Rules

- Prefer workspace-write over full-access.
- Use bounded subagents only for specialized exploration, governance review, or summaries.
- Keep subagent depth shallow and avoid recursive agent trees.
- Do not rely on hooks for critical control behavior on Windows.
- Any automation that may mutate files must be manually validated before being activated on a schedule.
- For Goblin program work, execute one phase at a time in dependency order.
- Do not advance to the next Goblin phase until the current phase has acceptance evidence recorded and the user explicitly asks to continue.
- Any Goblin phase-affecting change must update the phase tracking surfaces:
  - `Goblin/STATUS.md`
  - `Goblin/IMPLEMENTATION_TRACKER.md`
  - `Goblin/MATURITY.md`
  - `Goblin/EVOLUTION.md`
  - `Goblin/TAKEOVER_PLAN.md` when migration implications change
  - `codex.md`
- Treat `codex.md` as the Goblin operator playbook; keep it aligned with `AGENTS.md` and the Goblin state files.

## Validation

- After changes, run the relevant tests for the touched scope.
- Summaries must state:
  - files changed
  - tests run
  - artifacts written
  - status changes
  - assumptions made
