---
name: gitignore-audit
description: Audit the .gitignore for completeness against known sensitive file types and directories. Detect tracked files that should be ignored.
---

# Gitignore Audit

This skill verifies the `.gitignore` is complete and no sensitive files have
leaked into git tracking.

## When to Use

- When adding new file types to the project (e.g., `.log`, `.db`)
- When the publish-validation skill reports CONFIG findings
- During periodic security reviews
- Before a public release

## Workflow

1. **Read `.gitignore`** and verify all required patterns are present.
2. **Scan tracked files** for forbidden extensions and paths.
3. **Report** any gaps.

## Required `.gitignore` Patterns

These patterns must be present for a clean validation:

| Pattern | Reason |
|---------|--------|
| `.env` | Credential files |
| `.env.*` | Credential variants |
| `config/local.toml` | Machine-specific config overrides |
| `data/state/` | Runtime state (DuckDB, leases, idempotency) |
| `.codex/` | Local operator orchestration layer |
| `*.duckdb` / `*.duckdb.wal` | Database files |
| `*.exe` / `*.ex5` | Compiled binaries |
| `*.parquet` | Data files |
| `*.log` | Log files (may contain local paths in binary encoding) |
| `.vscode/` / `.idea/` | IDE configs |
| `*.egg-info/` | Build artifacts |

## Forbidden Tracked Files

Any tracked file matching these patterns is a finding:

- `data/state/**` — CRITICAL
- `.codex/**` — CRITICAL
- `.env` / `config/local.toml` — CRITICAL
- `*.exe` / `*.ex5` / `*.dll` — HIGH (binary)
- `*.duckdb` / `*.parquet` — HIGH (binary)
- `*.log` — HIGH (may contain unsanitizable binary paths)

## Remediation

```powershell
# Remove a file from tracking without deleting it:
git rm --cached path/to/file

# Then add to .gitignore and commit
```

## Rules

- Always preserve the file on disk — use `git rm --cached`, never `git rm`
- After fixing, re-run `python scripts/validate_for_publish.py --skip-tests`
