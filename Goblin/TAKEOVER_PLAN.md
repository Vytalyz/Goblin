# Goblin Takeover Plan

This document tracks the future clean takeover of the repo identity from `Agentic Forex` to `Goblin`.

## Objective

Move from:

- repo runtime kernel and identity centered on `agentic_forex`

to:

- repo identity, CLI surfaces, control plane, and eventually runtime namespace centered on `Goblin`

without breaking the working system during the transition.

## Current State

- Goblin is the umbrella program identity
- `src/agentic_forex` remains the runtime kernel
- Goblin docs and control-plane tracking already exist
- takeover stages T1 through T4 are completed with compatibility retained

## Migration Stages

### T0: Umbrella control plane

Current state.

- Goblin owns the program identity and tracking
- `agentic_forex` remains the actual kernel namespace
- dual identity exists intentionally

### T0.5: Operational readiness (P13–P15)

Prerequisite for T1. Ensures the inventory is cataloged, run logging captures session context, and clean-room rules are ratified before the namespace migration begins.

Exit criteria:

- `existing_goblin_coverage.md` produced with gap analysis
- `GoblinRunRecord` emitted by all campaign entrypoints with `session_window`
- clean-room rules ratified and baseline scenarios documented

### T1: Goblin becomes the primary operator-facing identity

Status: completed

Target:

- Goblin docs become the primary reference set
- Goblin CLI alias is supported everywhere relevant
- program status, phases, and approvals are referenced through Goblin first

Exit criteria:

- operators use Goblin documents and CLI first
- no new major control-plane surface is introduced under the legacy identity only

### T2: Compatibility bridge

Status: completed

Target:

- introduce compatibility shims so Goblin-facing imports or commands can coexist with `agentic_forex`
- preserve backward compatibility while renaming internal ownership boundaries

Exit criteria:

- legacy surfaces still work
- Goblin surfaces can replace them without ambiguity

### T3: Runtime namespace migration

Status: completed

Target:

- migrate packages, imports, and internal references from `agentic_forex` to Goblin-aligned naming
- keep temporary shims until parity is proven

Exit criteria:

- runtime behavior unchanged
- tests pass under the migrated namespace
- compatibility shims cover legacy callers

### T4: Clean takeover completion

Status: completed

Target:

- Goblin is the dominant identity in docs, CLI, packages, and control surfaces
- `agentic_forex` becomes deprecated compatibility only or is retired

Exit criteria:

- migration checklist complete
- deprecation path documented
- no critical dependency remains on the legacy namespace

## Post-Takeover: Multi-Timezone Strategy Program (S1+)

After T4 completes, the system supports sequential EUR/USD strategy development across forex sessions. Strategies are built one at a time through the full Goblin deployment ladder. See `PROGRAM.md` for strategy program rules.

This is not a migration concern — it is the operational use of the completed Goblin system.

## Takeover Guardrails

- no big-bang rename
- no runtime breakage in the name of cleanup
- maintain compatibility until the migrated path is proven
- update this document whenever a migration step changes
- do not claim Goblin takeover is complete until runtime, docs, CLI, and governance all align

