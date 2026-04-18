---
name: pre-push-validation
event: pre-push
description: "Run publish-guardian validation before any push to a remote branch."
timing:
  phase: before
  blocking: true
  timeout_ms: 120000
condition:
  tool_pattern: "*"
  file_pattern: "**"
action:
  type: script
  command: "python scripts/validate_for_publish.py --skip-tests"
on_failure: block
log_to: traces/pre-push-validation/
---

# Pre-Push Validation Hook

## Purpose

Block pushes that would introduce secrets, absolute user paths, tracked
binaries, log files, or MT5 terminal hashes into the repository.

## Implementation Status

### pre-commit (Local)

Implemented in `.pre-commit-config.yaml` as the `goblin-guardian-publish-gate`
hook with `stages: [pre-push]`. Activated by running:

```powershell
# Windows
.\scripts\setup-guardian.ps1

# Or manually
pre-commit install --hook-type pre-push
```

**Windows caveat**: Per `AGENTS.md`, git hooks have reliability issues on
Windows. The pre-push hook is a convenience, not a replacement for manual
validation. Always run the validation script manually before important pushes.

### GitHub Actions (CI)

Implemented in `.github/workflows/ci.yml`. Runs `validate_for_publish.py
--skip-tests`, `ruff check .`, `ruff format --check .`, and `pytest` on every
push and PR.

## Checks Performed

| # | Check | Severity |
|---|-------|----------|
| 1 | Secret scan (API keys, tokens, passwords) | CRITICAL |
| 2 | Absolute user paths (`C:\Users\...`) | HIGH |
| 3 | Tracked binaries (.exe, .ex5, .dll, .duckdb, .parquet) | HIGH |
| 4 | Tracked log files (.log) | HIGH |
| 5 | MT5 terminal hashes (32-char hex install identifiers) | HIGH |
| 6 | Sensitive dirs tracked (data/state/, .codex/) | CRITICAL |
| 7 | Local config tracked (.env, config/local.toml) | CRITICAL |
| 8 | Config hygiene (.gitignore completeness, templates) | MEDIUM–HIGH |
| 9 | Repo completeness (LICENSE, SECURITY.md, README.md) | HIGH |
| 10 | Sanitizer dry-run | HIGH |
| 11 | Test suite (when not skipped) | HIGH |
