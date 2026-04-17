# Runtime Provider Decision

## Decision Snapshot

- Date: `2026-03-20`
- Status: `active`
- Scope: phase-1 `Agentic Forex` research and validation

## Decision

- `Codex` is the builder and operator for this project, not the production runtime dependency.
- `Agentic Forex` must not assume a live OpenAI API dependency for phase 1.
- Phase-1 defaults remain:
  - deterministic research pipeline first
  - `mock` or manual review as the default agent layer
  - `OANDA` as the canonical research data source
  - `MT5` as downstream practice/parity validation only
- Any live LLM provider, including OpenAI, is optional and must be justified by measured research payoff relative to cost.

## Why This Decision Exists

- Chat and subscription usage should not be confused with programmable API billing.
- The platform already gets most of its practical value from deterministic work:
  - corpus ingestion
  - quality gating
  - strategy spec compilation
  - backtesting
  - stress testing
  - shadow ML
  - publish and approval flow
- A forced API dependency would increase recurring cost before proving that live model calls materially improve research outcomes.
- Using `Codex` as the development and research copilot preserves flexibility without hard-wiring the product runtime to one paid provider.

## Working Rule

- Do not introduce or expand live provider usage by default.
- Keep the provider abstraction in place, but treat it as optional infrastructure.
- Default the project to `mock` or deterministic behavior whenever the workflow can still produce useful artifacts.
- If a live provider is enabled later, it must stay behind the existing runtime abstraction and must not leak provider-specific assumptions into workflows, tools, or governance.

## Reflection Questions

- Did a live model materially improve candidate quality, review quality, or research throughput?
- Did the improvement hold up in backtest, stress, and review outputs?
- Was the improvement large enough to justify token cost and operational complexity?
- Could the same benefit have been achieved through better corpus digestion, better deterministic logic, or better human review prompts?

## Evidence That Would Justify Revisiting The Decision

- repeated cases where deterministic or mock-assisted discovery misses strong candidates that live model reasoning consistently surfaces
- repeated cases where live critic synthesis materially improves rejection quality or failure diagnosis
- measured cycle-time reduction without a drop in empirical validation quality
- a provider setup whose cost is acceptable relative to the value created

## Phase-1 Guardrails

- No live-provider-first architecture.
- No hidden dependency on ChatGPT product access.
- No runtime behavior that requires this Codex session to stay open.
- No promotion of ML-primary or LLM-primary signal generation in phase 1.

## Review Trigger

Revisit this decision only after enough evidence exists from real `EUR/USD` `scalping` and `day_trading` research loops to compare:

- deterministic or mock-assisted runs
- optional live-provider-assisted runs
- final empirical validation outcomes
