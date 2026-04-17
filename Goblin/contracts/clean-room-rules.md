# Clean-Room Rules

**Phase**: GOBLIN-P15  
**Status**: Ratified  
**Owner**: GoblinOrchestrator

## Purpose

Establish pattern-import discipline before any external framework, library, or methodology enters the Goblin system. These rules ensure that external patterns are evaluated on Goblin's terms — against Goblin's problems — rather than adopted because a framework happens to offer them.

## Rules

### Rule 1 — Problem-First Mapping

Every imported pattern must map to an **existing Goblin problem statement** first. The problem must be documented in the Goblin knowledge base or inventory before any solution pattern is considered.

**Audit check**: Does the pattern card reference a documented Goblin gap or problem ID?

### Rule 2 — Problem-Oriented Pattern Cards

Pattern cards describe the **Goblin problem** being solved, not the framework feature being adopted. The card title and abstract must be written in Goblin domain language.

**Audit check**: Does the card title reference Goblin concepts (session windows, deployment ladder, trial ledger) rather than framework concepts?

### Rule 3 — Governed Experiment Requirement

No framework code may enter the codebase without a **governed experiment** comparing it to the current Goblin implementation. The experiment must use the same evaluation gates and budget constraints as internal candidates.

**Audit check**: Does an experiment record exist with the pattern card as its parent reference?

### Rule 4 — Forex Session Boundary Mapping

No framework temporal model may be adopted without an **explicit mapping** to forex session boundaries (tokyo, london, overlap, new_york, off_hours). Generic time-series abstractions must demonstrate session-aware behavior.

**Audit check**: Does the experiment evidence include session-window-specific metrics?

### Rule 5 — Provenance Parity

External dependencies must satisfy the **same provenance and audit requirements** as internal artifacts. This includes version pinning, hash verification, and artifact lineage tracking.

**Audit check**: Is the dependency listed in the provenance registry with version, hash, and license?

### Rule 6 — Budget Governance

Pattern adoption is governed by **experiment accounting** — the same budget caps, suspension rules, and cost tracking that apply to internal strategy development. An external pattern gets no special budget treatment.

**Audit check**: Does the experiment consume budget from the same pool as internal experiments?

### Rule 7 — Inventory Deduplication

No pattern card may become an implementation without **inventory confirmation** that the capability doesn't already half-exist in the Goblin system. Reference the P13 operational inventory or its successor.

**Audit check**: Does the pattern card include a section citing the relevant inventory rows and confirming the gap?

## Enforcement

- Pattern cards are stored in `Goblin/reports/pattern_cards/`.
- Each card must pass all 7 audit checks before implementation begins.
- The governing experiment must complete evaluation before the pattern code is merged.
- Violations are recorded as governance incidents using the existing incident framework.

## Exceptions

No exceptions. These rules apply to all external patterns regardless of source, popularity, or perceived urgency.
