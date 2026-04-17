---
name: artifact-sanitization
description: Sanitize tracked artifact files to remove local paths, terminal hashes, and other machine-specific data before public push.
---

# Artifact Sanitization

This skill runs the path and hash sanitizer to strip locally-identifiable
information from tracked artifact files.

## When to Use

- Before any push to a public remote
- After generating new MT5 packets, compile logs, or trial ledger entries
- When the publish-validation skill reports PATH or TERMINAL_HASH findings
- After adding new experiment or approval artifacts

## Workflow

1. Run the sanitizer:
   ```
   python scripts/sanitize_paths_for_publish.py
   ```
2. Review the output — it reports files changed and replacements made.
3. If `--dry-run` is used, no files are modified; only a report is printed.
4. After sanitization, re-run publish validation to confirm the findings are resolved.

## What Gets Sanitized

| Pattern | Replacement |
|---------|-------------|
| Absolute user-home paths (Windows home dir) | `<USER_HOME>/...` |
| Repo root paths | Relative path or `.` |
| MetaQuotes AppData paths | `<MT5_APPDATA>/...` |
| MT5 Common Files paths | `<MT5_COMMON_FILES>/...` |
| MT5 terminal hashes (32-char hex) | `<MT5_TERMINAL_HASH>` |
| All of the above in lowercase variants | Same placeholders |
| JSON double-escaped backslash variants | Same placeholders |

## Covered File Types

`.json`, `.md`, `.jsonl`, `.log`, `.ini`, `.py`, `.txt`, `.csv`

## Skipped Directories

`data/`, `.git/`, `.venv/`, `.codex/`, `__pycache__/`, `traces/`, `reports/`,
`published/`, `dist/`, `build/`

These directories are either gitignored or contain only gitignored files.

## Rules

- Never commit unsanitized artifacts to a branch that will be pushed
- The sanitizer is idempotent — running it twice produces the same result
- Binary files (e.g., Unicode-encoded `.log`) are not processed; they must be gitignored
- The sanitizer script itself is allowlisted from path scanning
