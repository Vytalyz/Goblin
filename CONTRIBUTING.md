# Contributing to Goblin

Welcome! Goblin is a governed, agentic algorithmic forex research platform. All contributions are protected by the **Goblin Guardian** agent — a layered QA, lint, and security gate that runs on every commit, push, and PR.

## Quick Setup

### Windows (PowerShell)

```powershell
git clone https://github.com/Vytalyz/Goblin.git
cd Goblin
python -m venv .venv
.venv\Scripts\Activate.ps1
.\scripts\setup-guardian.ps1
```

### Linux / macOS (Bash)

```bash
git clone https://github.com/Vytalyz/Goblin.git
cd Goblin
python -m venv .venv
source .venv/bin/activate
bash scripts/setup-guardian.sh
```

The setup script installs all dev dependencies, activates pre-commit hooks, and registers the pre-push validation gate.

## What Guardian Checks

### On Every Commit (pre-commit)

| Check | Tool | What it catches |
|-------|------|-----------------|
| **Ruff Lint** | `ruff check .` | Style violations, unused imports, bad patterns |
| **Format Check** | `ruff format --check` | Inconsistent formatting |
| **Syntax Check** | `python -m compileall .` | Python syntax errors |
| **Test Gate** | `pytest --tb=short -q` | Broken tests |
| YAML validation | `check-yaml` | Malformed YAML |
| Whitespace | `trailing-whitespace`, `end-of-file-fixer` | Trailing whitespace, missing newlines |

### On Every Push (pre-push)

| Check | Tool | What it catches |
|-------|------|-----------------|
| **Publish Validation** | `validate_for_publish.py` | Secrets, absolute paths, binaries, MT5 hashes, sensitive dirs, config hygiene, repo completeness |

### In CI (GitHub Actions)

All of the above run in CI on every push to `main` and every pull request. The CI job is named **Goblin Guardian** and writes a summary to the PR checks tab.

## Running Checks Manually

```powershell
# Run all pre-commit checks
pre-commit run --all-files

# Run lint only
ruff check .

# Run format check only
ruff format --check .

# Run full publish validation (with tests)
python scripts/validate_for_publish.py

# Run publish validation (skip tests)
python scripts/validate_for_publish.py --skip-tests

# Run tests
python -m pytest
```

## Auto-Fix (Opt-In)

Guardian **never** auto-fixes code in hooks — it only reports issues. To apply automatic fixes manually:

```powershell
# Fix lint issues
ruff check --fix .

# Format code
ruff format .

# Sanitize artifact paths
python scripts/sanitize_paths_for_publish.py
```

Always run tests after auto-fixing to confirm nothing broke.

## Bypassing Guardian (Discouraged)

In rare cases you may need to skip hooks temporarily:

```powershell
git commit --no-verify -m "emergency fix"
```

**This bypasses all local checks.** CI will still catch issues on push/PR. Do not make this a habit — Guardian exists to protect the codebase.

## Commit & PR Guidelines

1. Fork the repository and create a feature branch from `main`
2. Make your changes and ensure all Guardian checks pass locally
3. Run `python scripts/validate_for_publish.py` before pushing
4. Open a pull request — CI will run all Guardian checks automatically
5. PRs with CRITICAL or HIGH findings will not be merged

### What Must Not Be Committed

- `.env` or `config/local.toml` (use `.env.example` and `config/local.toml.example` as templates)
- Files under `data/state/` or `.codex/`
- Binary files (`.exe`, `.ex5`, `.dll`, `.duckdb`, `.parquet`)
- Log files (`.log`)
- Absolute user paths (`C:\Users\...`)
- API keys, tokens, or passwords (inline or in config files)

### Portfolio Slots

The portfolio currently exposes two mutable slots, `slot_a` (active candidate) and `slot_b` (blank-slate challenger), defined in `config/portfolio_policy.toml`. Strategies progress through the S1–S6 development loop and may rotate between slots once they pass the gates. There is no candidate locked from mutation today; see [AGENTS.md](AGENTS.md) for the active governance rules.

## Troubleshooting Guardian Failures

### `[CRITICAL] SECRET: Potential secret found`

You have an API key, token, or password in a tracked file.

**Fix:** Move secrets to `.env` (which is gitignored). Use environment variables in code. If the secret was already committed, rotate it immediately and clean git history.

### `[HIGH] PATH: Absolute user path found`

A file contains a hardcoded absolute user path.

**Fix:** Run `python scripts/sanitize_paths_for_publish.py` to clean artifact files. For source code, use relative paths or `Path(__file__).parent` patterns.

### `[HIGH] BINARY: Binary file tracked`

A compiled binary (`.exe`, `.ex5`, `.dll`, `.duckdb`, `.parquet`) is tracked by git.

**Fix:**
```bash
git rm --cached path/to/file.exe
echo "path/to/file.exe" >> .gitignore
```

### `[HIGH] TERMINAL_HASH: MT5 terminal hash`

An MT5 terminal install identifier (32-char hex string) is in a tracked file.

**Fix:** Run `python scripts/sanitize_paths_for_publish.py` to strip terminal hashes from artifacts.

### `[HIGH] LOG_FILE: Log/temp file tracked`

A `.log` file is tracked by git. These may contain binary-encoded local paths.

**Fix:**
```bash
git rm --cached path/to/file.log
```
Ensure `*.log` is in `.gitignore`.

### `[HIGH] COMPLETENESS: Missing LICENSE/SECURITY.md/README.md`

A required repository file is missing.

**Fix:** Ensure `LICENSE`, `SECURITY.md`, and `README.md` exist at the repo root.

### `[HIGH] CONFIG: Missing required gitignore pattern`

The `.gitignore` is missing a pattern that protects sensitive files.

**Fix:** Add the missing pattern to `.gitignore`. Required patterns: `.env`, `config/local.toml`, `data/state/`, `.codex/`, `*.log`.

### `[HIGH] SANITIZER: Unsanitized paths in artifact files`

The sanitizer dry-run found files that still contain local paths or hashes.

**Fix:** Run `python scripts/sanitize_paths_for_publish.py` and re-validate.

### `[CRITICAL] SENSITIVE_DIR/FILE: File in forbidden tracked directory`

A file under `data/state/`, `.codex/`, or `.env` is tracked by git.

**Fix:**
```bash
git rm --cached path/to/sensitive/file
```
Verify the directory is in `.gitignore`.

### `[HIGH] TESTS: Test suite failed`

One or more tests are failing.

**Fix:** Run `python -m pytest -v` to see which tests fail and why. Fix the failing tests before committing.

### Ruff Lint / Format failures

**Fix:** Run `ruff check --fix .` for lint issues and `ruff format .` for formatting. Review changes before committing.

## Branch Protection

The `main` branch is protected. Recommended settings:

- **Require status checks to pass** — the Goblin Guardian CI job must succeed
- **Require pull request reviews** — at least one approval before merge
- **No force pushes** — history must not be rewritten on `main`
- **No deletions** — `main` cannot be deleted

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting policy.

## License

See [LICENSE](LICENSE) for terms.
