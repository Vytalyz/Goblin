# Playground Repo Isolation Incident - 2026-04-14

## Scope

This ledger captures the repository-boundary incident affecting sibling folders under `<USER_HOME>/OneDrive\Documents\Playground`.

The immediate goals are to:

1. Prove the current git authority for `Prophet` and `Agentic Forex`.
2. Record any cross-project discrepancy that must be reverted, moved, or revalidated.
3. Establish the safe sequence for converting real project folders into standalone git repositories.

## Boundary Findings

### Shared Root Evidence

- `Playground/.git` exists and is the active git root for `Prophet` and `Agentic Forex`.
- Running `git rev-parse --show-toplevel` from `Prophet` resolves to `<USER_HOME>/OneDrive/Documents/Playground`.
- Running `git rev-parse --show-toplevel` from `Agentic Forex` resolves to `<USER_HOME>/OneDrive/Documents/Playground`.
- `Prophet/.git` does not exist.
- `Agentic Forex/.git` does not exist.
- `Agentic Forex-2/.git` exists and resolves to its own local repo root.

### Consequence

`Prophet` and `Agentic Forex` are structurally independent projects but are not currently isolated in version control. Repo-aware tools executed inside either folder can surface sibling changes from the shared `Playground` root.

## Top-Level Playground Inventory

The following classification is based on current filesystem evidence only.

| Folder | Classification | Git State | Notes |
| --- | --- | --- | --- |
| `Agentic Forex` | project | nested under `Playground` | Has `pyproject.toml` and `AGENTS.md`; should become standalone. |
| `Prophet` | project | nested under `Playground` | Has `pyproject.toml` and `AGENTS.md`; should become standalone. |
| `Agentic Forex-2` | existing standalone repo | local `.git` present | Already isolated; validate but do not reinitialize. |
| `Agentic Forex-2-gap-lane` | worktree | `.git` file/dir present | Treat as linked to `Agentic Forex-2`; validate separately. |
| `Agentic Forex-2-overlap-benchmark` | worktree | `.git` file/dir present | Treat as linked to `Agentic Forex-2`; validate separately. |
| `Agentic Forex-2-overlap-challenger` | worktree | `.git` file/dir present | Treat as linked to `Agentic Forex-2`; validate separately. |
| `Forex` | candidate project | nested under `Playground` | Has `pyproject.toml` and `AGENTS.md`; ownership still needs confirmation. |
| `Investment Strategy` | candidate project | nested under `Playground` | Has `pyproject.toml`; ownership still needs confirmation. |
| `DND-world` | candidate project/content repo | nested under `Playground` | Has `AGENTS.md`; ownership still needs confirmation. |
| `gnidart` | existing standalone repo | local `.git` present | Validate separately. |
| `.codex-tmp`, `.npm-cache`, `.venv`, `tmp` | non-project utility/cache | no project repo needed | Exclude from standalone repo creation. |

## Initial Discrepancies

### D-001: Prophet uses the wrong git root

- Evidence: `git rev-parse --show-toplevel` from `Prophet` returns `Playground`.
- Evidence: `git status --short` from `Prophet` surfaces sibling folders such as `../Agentic Forex/`, `../DND-world/`, and `../Forex/`.
- Status: remediated on `2026-04-14` by running `git init -b main` inside `Prophet`.
- Verification: `git rev-parse --show-toplevel` from `Prophet` now resolves to `<USER_HOME>/OneDrive/Documents/Playground/Prophet`.

### D-002: Agentic Forex uses the wrong git root

- Evidence: `git rev-parse --show-toplevel` from `Agentic Forex` returns `Playground`.
- Evidence: `git status --short` from `Agentic Forex` surfaces sibling folders such as `../Prophet/`, `../DND-world/`, and `../Forex/`.
- Status: remediated on `2026-04-14` by running `git init -b main` inside `Agentic Forex`.
- Verification: `git rev-parse --show-toplevel` from `Agentic Forex` now resolves to `.`.

### D-003: Shared Playground status obscures ownership

- Evidence: `git status --short` at `Playground` reports multiple sibling directories as untracked at once, including `Agentic Forex/`, `Prophet/`, `Forex/`, and worktree folders.
- Risk: wrong-repo commits, false assumptions about what changed, and accidental completion markers being recorded under the wrong authority.
- Current state: `Playground/.git` still exists, but `Prophet` and `Agentic Forex` no longer resolve to it because they now have local git roots.
- Remaining action: decide whether the parent `Playground` repo should be retired, ignored operationally, or left as a container-only repo.

### D-004: Agentic Forex-2 is already isolated but dirty

- Evidence: `Agentic Forex-2` resolves to its own git root and shows local modifications.
- Required action: keep out of the current rollback path except for validation that its repo boundary remains intact.

## Project Integrity Findings

### Prophet

#### P-001: planning surfaces are internally inconsistent

- `STATUS.md` reports Bundles A and B complete, an open phase set of `9, 10, 11, 12`, and `39 tests passed`.
- `PHASE_PLAN.md` agrees that open phases are `9`, `10`, `11`, and `12`.
- `PLAN.md` still says Bundle B is the active next bundle and cites `38 passing tests`.
- Status: remediated on `2026-04-14` by aligning `PLAN.md` to the verified Bundle B completion state and `39 passing tests` checkpoint.
- Current classification: resolved planning drift inside Prophet, not evidence of forex contamination.

#### P-002: no direct forex-content spillover found in Prophet

- Recursive content search found only intentional planning references to Goblin or Agentic Forex as architectural influences.
- No direct `AF-CAND`, `OANDA`, or `MT5` payload-style content was found in Prophet during the initial spillover search.
- Current classification: boundary incident without confirmed forex artifact pollution inside Prophet content.

#### P-003: Prophet validation is environment-dependent

- `Prophet` does not currently have a local `.venv` directory.
- Prophet tests were nevertheless run successfully from the Agentic Forex Python environment in a prior terminal trace, first at `38 passed` and then at `39 passed` after the continuity test expansion.
- Current classification: validation path exists, but it is not yet isolated to a Prophet-local environment.
- Required action: decide whether Prophet should keep using a shared Python environment temporarily or receive a local environment as part of repo isolation.

### Agentic Forex

#### A-001: phase checkpoint coverage currently matches status claims

- `Goblin/STATUS.md` claims 20 completed phases/checkpoints: `GOBLIN-P00` through `GOBLIN-P15`, plus `GOBLIN-T1` through `GOBLIN-T4`.
- `Goblin/checkpoints/` currently contains 20 phase directories matching those claims.
- Current classification: no immediate evidence that the shared repo boundary changed Agentic Forex phase completion state.

#### A-002: future-dated milestone exists in `Goblin/EVOLUTION.md`

- `Goblin/EVOLUTION.md` contains a milestone dated `2026-06-14` even though the current incident date is `2026-04-14`.
- Validation result: the milestone has a matching backing artifact at `Goblin/reports/phase_validation_audit_20260614.md`.
- Current classification: pre-existing historical or future-dated audit artifact, not evidence of repo-boundary corruption.
- Action taken: retained as-is and captured in this ledger; no rollback was applied during boundary recovery.

#### A-003: recent human approvals bypass structured attestation fields

- Recent `approvals/approval_log.jsonl` entries for `AF-CAND-0730` and `AF-CAND-0733` have `source: human` with empty `evidence_paths`, null `policy_snapshot_hash`, null `evidence_fingerprint`, null `approval_idempotency_key`, and empty `attestation` objects.
- Earlier policy-engine records in the same log include populated evidence, hashes, idempotency keys, and attestation booleans.
- Validation result: `ApprovalRecord` permits those fields to be absent for human approvals, and `approval_status()` only enforces populated freshness checks when those values are present.
- Current classification: schema-valid but lower-provenance human approval records, not evidence of wrong-repo contamination.
- Action taken: retained as-is and captured as a governance-hardening follow-up rather than a rollback item.

#### A-004: no Prophet-content spillover found in Agentic Forex beyond this incident audit

- The direct spillover search did not produce Prophet-world content inside Agentic Forex prior to creation of this incident ledger.
- Current classification: boundary incident without confirmed Prophet content pollution inside Agentic Forex source or governance content.

## Generated Audit Artifacts

- `docs/audit/playground-repo-isolation-incident-2026-04-14.md` — human-readable incident ledger and discrepancy tracker.
- `docs/audit/playground-repo-boundary-report-2026-04-14.json` — machine-readable top-level folder audit generated by `scripts/audit_playground_repo_boundaries.py`.

## Current Boundary State

The latest generated report classifies the top-level Playground folders as follows:

- standalone repos: `Agentic Forex`, `Agentic Forex-2`, `DND-world`, `Fallen-Kingdoms-Obsidian`, `Financial Planning`, `Forex`, `gnidart`, `Investment Strategy`, `Prophet`
- git worktrees: `Agentic Forex-2-gap-lane`, `Agentic Forex-2-overlap-benchmark`, `Agentic Forex-2-overlap-challenger`
- folders still nested under the shared Playground root: utility/cache areas only

## Remaining Recovery Work

1. Decide whether the parent `Playground/.git` should be retired or simply ignored operationally now that the child project folders have their own local repos.
2. Optionally harden the approval policy so future human approvals carry stronger provenance fields.
3. Re-run the boundary audit after any additional discrepancy fixes.

## Protected Surfaces

The following files require explicit verification before any rollback or cleanup affecting their project:

### Agentic Forex

- `AGENTS.md`
- `codex.md`
- `Goblin/STATUS.md`
- `Goblin/IMPLEMENTATION_TRACKER.md`
- `Goblin/MATURITY.md`
- `Goblin/EVOLUTION.md`
- `Goblin/TAKEOVER_PLAN.md`
- `approvals/approval_log.jsonl`

### Prophet

- `PLAN.md`
- `STATUS.md`
- `PHASE_PLAN.md`
- `IMPLEMENTATION_TRACKER.md`
- `AGENTS.md`
- `codex.md`
- `PROPHET.md`
- `canon-manifest.json`

## Execution Order

1. Build per-project discrepancy tables for `Agentic Forex` and `Prophet`.
2. Verify protected surfaces before any repo initialization.
3. Identify any wrong-repo artifacts or incorrectly completed planning/status markers.
4. Revert or relocate only confirmed discrepancies.
5. Initialize standalone repos for audited project folders.
6. Re-run repo-root and project validation checks after repo creation.

## Open Questions

- Whether `Forex`, `Investment Strategy`, and `DND-world` should also become standalone repos in this same recovery pass.
- Whether `Playground/.git` should be deleted after migration or retained only as a non-project container repo.
- Whether any historical commits or external backups exist outside the current parent repo state.