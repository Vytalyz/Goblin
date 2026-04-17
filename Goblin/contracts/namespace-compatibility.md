# Namespace Compatibility Contract

Phase chain: GOBLIN-T2 -> GOBLIN-T4

## Purpose

Define compatibility guarantees while the runtime namespace transitions from `agentic_forex` to `goblin`.

## Guarantees

1. Goblin-primary imports are supported for operator-facing surfaces.
2. Legacy `agentic_forex` imports remain functional during transition.
3. CLI commands remain callable through both `goblin` and `agentic-forex` entrypoints.
4. Backward compatibility is implemented as wrappers/aliases, not divergent logic.
5. All compatibility bridges must preserve deterministic runtime behavior.

## Current Bridge Implementation

- Primary namespace package: `src/goblin/`
- Legacy namespace package: `src/agentic_forex/` (compatibility retained)
- `src/goblin/__init__.py` aliases core runtime subpackages from `agentic_forex`
- `src/goblin/cli/app.py` forwards to the established CLI implementation
- `src/goblin/__main__.py` enables `python -m goblin`

## Deprecation Policy

- New operator-facing docs and examples must prefer `goblin` naming.
- New compatibility code must avoid introducing additional legacy-only surfaces.
- Legacy namespace retirement is allowed only after all critical external callers are migrated.
