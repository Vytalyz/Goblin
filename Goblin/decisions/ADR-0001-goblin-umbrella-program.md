# ADR-0001: Goblin Umbrella Program

## Context

The repo already contains a deterministic `agentic_forex` kernel plus operator, campaign, portfolio, governance, runtime, and MT5 surfaces. A big-bang package rename would add migration risk before the reliability stack is stable.

## Decision

Adopt Goblin as the umbrella program identity at the documentation, control-plane, and workflow layer. Keep `src/agentic_forex` as the runtime kernel during early phases. Add a `goblin` CLI alias and Goblin tracking state under `/Goblin`.

## Consequences

- Goblin becomes the canonical program identity immediately.
- The Python namespace rename is deferred until platform stability and compatibility shims exist.
- Operator and orchestrator concerns stay separate.
