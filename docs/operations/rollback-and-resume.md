# Rollback & Resume Procedures — Architecture Migration

**Generated:** 2026-04-13  
**Phase:** 5 — Operational Resilience  
**Scope:** Migration batch rollback and resume after interruption

---

## Principles

1. Every migration batch is independently revertible
2. Partial completion is always safe — no batch leaves the system in a broken intermediate state
3. Rollback uses `git checkout` for tracked files, `git clean` for new files
4. Resume requires only knowing which batch last succeeded

---

## Rollback Procedures

### Per-Batch Rollback

Each batch in `docs/migration/rename-and-rewire-plan.md` specifies its own rollback command. The general pattern:

```powershell
# Revert modifications to tracked files
git checkout -- <paths-modified-by-batch>

# Remove new files created by batch
git clean -fd <paths-created-by-batch>

# Verify
python -m pytest tests/ -x --tb=short
```

### Batch-Specific Commands

| Batch | Rollback Command |
|-------|-----------------|
| 1 (delete duplicates) | `git checkout -- .codex/skills-src/` |
| 2 (archive legacy) | `git checkout -- skills/; git clean -fd docs/archive/` |
| 3 (provider adapters) | `git clean -fd .agents/hooks/ .github/; git checkout -- .vscode/mcp.json` |
| 4 (canonical agents) | `git clean -fd .agents/agents/` |
| 5 (TOML adapters) | `git checkout -- .codex/agents/` |
| 6 (identity rename) | `git checkout -- AGENTS.md codex.md README.md .codex/rules/ .agents/skills/ automations/prompts/` |
| 7 (fix paths) | `git checkout -- config/default.toml tests/test_cli_and_boundaries.py src/agentic_forex/mt5/ea_generator.py` |
| 8 (vendor coupling) | `git checkout -- src/agentic_forex/workflows/contracts.py src/agentic_forex/forward/readiness.py config/default.toml` |
| 9 (workflow governance) | `git checkout -- workflows/` |
| 10 (registry) | `git clean -fd .agents/registry.json` |
| 11 (industry update) | `git clean -fd .agents/skills/industry-monitoring/ src/agentic_forex/industry/ reports/industry-update/; git checkout -- src/agentic_forex/cli/app.py src/goblin/__init__.py` |
| 12 (GOBLIN.md) | `git clean -fd GOBLIN.md` |

### Full Rollback (Nuclear Option)

```powershell
# Revert all tracked changes
git checkout .

# Remove all untracked files created during migration
git clean -fd docs/ .agents/agents/ .agents/hooks/ .github/ reports/industry-update/ GOBLIN.md

# Verify clean state
python -m pytest tests/ -x --tb=short
```

**Warning:** This reverts ALL uncommitted work, not just migration changes. Use per-batch rollback when possible.

---

## Resume Procedures

### Determine Last Successful Batch

```powershell
# Check for the presence of batch outputs in order
# Batch 1: should NOT have .codex/skills-src/
Test-Path .codex/skills-src/

# Batch 2: should NOT have skills/
Test-Path skills/

# Batch 3: should have these files
Test-Path .agents/hooks/README.md
Test-Path .vscode/mcp.json
Test-Path .github/copilot-instructions.md

# Batch 4: should have 17 files in .agents/agents/
(Get-ChildItem .agents/agents/ -Filter "*.md" | Measure-Object).Count

# Batch 5: check for canonical_ref in TOML
Select-String -Path ".codex/agents/*.toml" -Pattern "canonical_ref"

# Batch 6: check identity rename
Select-String -Path "AGENTS.md" -Pattern "Agentic Forex"

# Batch 7: check hardcoded paths
Select-String -Path "config/default.toml" -Pattern "C:\\Users"

# Batch 8: check vendor coupling
Select-String -Path "config/default.toml" -Pattern "goblin-practice"

# Batch 9: check workflow governance
Select-String -Path "workflows/*.json" -Pattern "trigger"

# Batch 10: check registry
Test-Path .agents/registry.json

# Batch 11: check industry update
Test-Path src/agentic_forex/industry/report.py

# Batch 12: check GOBLIN.md
Test-Path GOBLIN.md
```

### Resume Protocol

1. Run the detection script above to find the last completed batch
2. Run `python -m pytest tests/ -x --tb=short` to confirm current state is healthy
3. Continue from the next batch number
4. If current state is unhealthy, rollback the last batch, fix, then resume

### Interrupted Batch

If a batch was partially completed (e.g., 10 of 17 agent files created):

1. Rollback the entire batch: `git clean -fd .agents/agents/` (for Batch 4)
2. Re-run the batch from scratch
3. Do NOT attempt to complete a partial batch manually

---

## Commit Strategy

### Recommended

Commit after each successful batch with a conventional message:

```
goblin-migration: batch-N — <description>
```

Examples:
```
goblin-migration: batch-1 — delete duplicate skills from .codex/skills-src
goblin-migration: batch-4 — create 17 canonical agent definitions
goblin-migration: batch-6 — rename Agentic Forex → Goblin in docs
```

### Benefits

- `git revert <commit>` rolls back a single batch cleanly
- `git bisect` can identify which batch introduced a regression
- Clear audit trail for governance

### Alternative: Branch Strategy

```powershell
git checkout -b goblin-migration/phase-4
# run all batches
# squash or merge when complete
```

---

## Health Checks

Run after every batch and after any resume:

```powershell
# 1. Tests pass
python -m pytest tests/ -x --tb=short

# 2. CLI starts
python -m goblin --help
python -m agentic_forex --help

# 3. Import bridge works
python -c "from goblin.config import settings; print('OK')"

# 4. No orphaned references (run after Batch 6+)
Select-String -Path "*.md","config/*.toml",".agents/**/*.md" -Pattern "Agentic Forex" -Recurse | Where-Object { $_.Path -notmatch "src[\\/]|data[\\/]|reports[\\/]|traces[\\/]|experiments[\\/]|\.git[\\/]|docs[\\/]archive" }
```
