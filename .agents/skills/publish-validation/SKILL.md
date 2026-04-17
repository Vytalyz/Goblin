---
name: publish-validation
description: Validate the repository is safe for public GitHub push. Run before any commit that will be pushed. Combines QA, senior engineering, and security review into a single deterministic gate.
---

# Publish Validation

This skill runs the pre-publish validation gate and interprets the results.

## When to Use

- Before pushing to GitHub (any branch)
- Before creating a pull request
- After sanitizing paths or editing config files
- When the user asks "is it safe to push?"
- As part of any Phase 5/6 publish workflow

## Workflow

1. Run the deterministic validation script:
   ```
   python scripts/validate_for_publish.py --skip-tests
   ```
2. Parse the output for finding counts by severity (CRITICAL, HIGH, MEDIUM).
3. If CRITICAL or HIGH findings exist:
   - List each finding with file path, line number, and description
   - Provide specific remediation steps for each
   - Do NOT proceed with push
4. If only MEDIUM findings exist:
   - List them for user review
   - Recommend resolution but do not block
5. If no findings:
   - Confirm the repository is safe to push
   - Optionally run with tests: `python scripts/validate_for_publish.py`

## Checks Performed

| # | Check | Severity if Failed |
|---|-------|--------------------|
| 1 | Secret scan (API keys, tokens, passwords) | CRITICAL |
| 2 | Absolute user paths (`C:\Users\...`) | HIGH |
| 3 | Tracked binaries (.exe, .ex5, .dll, .duckdb, .parquet) | HIGH |
| 4 | Tracked log files (.log) | HIGH |
| 5 | MT5 terminal hashes (32-char hex install identifiers) | HIGH |
| 6 | Sensitive dirs tracked (data/state/, .codex/) | CRITICAL |
| 7 | Local config tracked (.env, config/local.toml) | CRITICAL |
| 8 | Config hygiene (.gitignore completeness, templates) | MEDIUM–HIGH |
| 9 | Repo completeness (LICENSE, SECURITY.md, README.md) | HIGH |
| 10 | Sanitizer dry-run (unsanitized artifact paths) | HIGH |
| 11 | Test suite (pytest) | HIGH |

## Auto-Fix

The `--fix` flag runs the path sanitizer automatically when unsanitized
artifact paths are found:
```
python scripts/validate_for_publish.py --fix --skip-tests
```

## Rules

- The script at `scripts/validate_for_publish.py` is the single source of truth.
- Never bypass the gate by pushing without running validation.
- CRITICAL and HIGH findings are blocking — no exceptions without user override.
- The validation script itself is allowlisted from path-pattern scanning.
- `.env.example` and `config/local.toml.example` are allowlisted templates.
