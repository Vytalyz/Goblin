# Goblin — Copilot Instructions

This is the **Goblin** algorithmic forex research platform.

## Key Rules

- See `AGENTS.md` for the complete governance policy.
- The deterministic kernel lives in `src/agentic_forex/` — do not rename it without explicit migration authorization.
- `src/goblin/` is a bridge namespace that aliases to `agentic_forex` via `sys.modules`.
- Both `goblin` and `agentic-forex` CLI entry points exist and resolve to the same `main()`.
- OANDA is the canonical research data source. MT5 is practice/parity only.
- Governed MT5 demo-account EA automation is allowed for live-demo observability and broker reconciliation.
- Real-money automated trading remains forbidden unless explicitly reauthorized by repo governance.
- The portfolio has two mutable slots: `slot_a` (active candidate, currently `AF-CAND-0733`) and `slot_b` (blank-slate challenger). Strategies progress through the S1–S6 development loop documented in the strategy development plan.

## Project Structure

- `.agents/` — canonical agentic component definitions (agents, skills, hooks)
- `src/agentic_forex/` — deterministic Python kernel
- `src/goblin/` — bridge namespace
- `Goblin/` — program control plane (status, phases, incidents, runbooks)
- `config/` — TOML policy files
- `workflows/` — JSON node-based workflow definitions
- `GOBLIN.md` — canonical system document
