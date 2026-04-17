---
name: pre-push-validation
event: pre-commit
description: "Run publish-guardian validation before any commit on a push-targeted branch."
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

Block commits that would introduce secrets, absolute user paths, tracked
binaries, log files, or MT5 terminal hashes into the repository.

## Implementation Notes

This hook is defined as a **contract** — provider-specific implementations
vary:

### GitHub Actions (CI)

Already implemented in `.github/workflows/ci.yml`. Runs
`validate_for_publish.py --skip-tests` then `pytest` on every push and PR.

### Local Git Hook

On Windows, git hooks have reliability issues (see `AGENTS.md`: "Do not rely
on hooks for critical control behavior on Windows"). The recommended workflow
is to run the validation script manually:

```powershell
python scripts/validate_for_publish.py --skip-tests
```

If you want a local pre-push hook as a convenience (not a replacement for
manual validation):

```bash
#!/bin/sh
# .git/hooks/pre-push
python scripts/validate_for_publish.py --skip-tests
```

### Claude Code / Codex

Provider-specific hook implementations can wire this contract into
`pre-tool-use` events for write operations.

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
