# Goblin Program

Goblin is the umbrella reliability, validation, and intelligence program for the forex agentic system. It is the tracked control-plane program that sits over the existing deterministic kernel in `src/agentic_forex`.

## Tracking Documents

Use these documents together:

- `Goblin/ROADMAP.md`: planned execution order
- `Goblin/S1_PLUS_PLAN.md`: remaining post-takeover execution plan
- `Goblin/STATUS.md`: current tracked status
- `Goblin/IMPLEMENTATION_TRACKER.md`: what is actually implemented vs partial vs scaffolded
- `Goblin/MATURITY.md`: subsystem maturity levels
- `Goblin/EVOLUTION.md`: major milestones and evolution order
- `Goblin/TAKEOVER_PLAN.md`: future clean takeover from `Agentic Forex` to `Goblin`

## Program Intent

Goblin exists to stop truth drift, preserve executable validation, govern incidents, and make long-running strategy work resumable phase by phase. It is designed so the repo can recover cleanly after interruptions, usage limits, or failed runs.

## Control Split

- `GoblinOrchestrator`: machine-facing workflow controller for phase sequencing, dependency gating, idempotent reruns, checkpoints, and resumability.
- `GoblinOperator`: human/Codex-facing supervisory layer for evidence assembly, status summaries, approval surfaces, incident framing, and decision support.

## Decision-Specific Truth Stack

- `research_backtest`: research truth
- `mt5_replay`: executable validation truth
- `live_demo`: operational truth
- `broker_account_history`: reconciliation truth

These channels do not answer the same question, and Goblin does not require them to match in the same way. Research <-> MT5 is structural, MT5 <-> live is strict executable parity, and live <-> broker is strict reconciliation.

## Phase Execution Rules

- Every phase is checkpointed.
- Every phase can be resumed from its last verified checkpoint.
- Authoritative artifacts must be preserved; regenerable artifacts may be rebuilt.
- A phase cannot be claimed complete until its exit criteria and acceptance checks are satisfied.
- Any material unexplained delta between required channels must open or keep open an incident.
- Execute one phase at a time in sequence.
- At the end of a phase, update the tracking documents and stop for user confirmation before continuing to the next phase.

## Kernel Boundary

Goblin is the umbrella control plane. The existing `src/agentic_forex` package remains the deterministic runtime kernel until a later migration phase explicitly replaces it. The repo must remain valid and resumable even if Codex is closed.

## Multi-Timezone Strategy Program

After Goblin reaches full operational status (P13–P15 complete, T1–T4 takeover complete), the repo supports a sequential EUR/USD strategy program targeting different forex session windows (London open, London/NY overlap, US session, etc.).

Program rules:

- One strategy built and validated at a time through the full deployment ladder.
- A strategy must reach `eligible_for_replacement` before the next strategy begins development.
- Each strategy enters P10 portfolio governance as a new slot with its own session scope.
- Session-aware run records (P14) provide root-cause evidence per session window.
- Clean-room rules (P15) govern any external pattern adoption during strategy development.
- When multiple successful strategies coexist, portfolio governance extends to handle session-scoped coordination.

Execution of the remaining program is defined in `Goblin/S1_PLUS_PLAN.md` and should be tracked with bundle checkpoints rather than ad hoc next steps.
