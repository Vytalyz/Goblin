# Guardian for Forks

How to reuse the Goblin Guardian QA setup in a fork or new project.

## Files That Constitute Guardian

| File | Purpose |
|------|---------|
| `.pre-commit-config.yaml` | Pre-commit and pre-push hook definitions |
| `scripts/validate_for_publish.py` | Deterministic publish-validation gate |
| `scripts/sanitize_paths_for_publish.py` | Artifact path sanitizer |
| `scripts/setup-guardian.ps1` | One-command Windows setup |
| `scripts/setup-guardian.sh` | One-command Linux/macOS setup |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline |
| `pyproject.toml` (`[tool.ruff]` + dev deps) | Ruff config and dev dependencies |
| `CONTRIBUTING.md` | Contributor documentation |

## Adapting for a New Project

### 1. Copy the Guardian files

Copy all files listed above into your new project.

### 2. Adjust `validate_for_publish.py`

The validation script has Goblin-specific patterns. Customize:

- `SECRET_PATTERNS` — adjust for your project's secret formats
- `PATH_PATTERNS` — keep as-is (catches Windows absolute paths)
- `BINARY_EXTENSIONS` — add/remove extensions for your project
- `FORBIDDEN_TRACKED_PREFIXES` — change to your sensitive directories
- `FORBIDDEN_TRACKED_FILES` — change to your local config files
- `ALLOWLISTED_FILES` — files expected to contain path-like patterns
- `SKIP_SCAN_DIRS` — directories too large or irrelevant to scan

### 3. Adjust `.pre-commit-config.yaml`

- Keep the ruff hooks as-is (they work for any Python project)
- Update the publish-gate hook path if you move the script
- Adjust the test command if you use a different test runner

### 4. Adjust `pyproject.toml` ruff config

- Update `target-version` to your minimum Python version
- Adjust `line-length` to your preference
- Add or remove rule sets in `[tool.ruff.lint] select`

### 5. Adjust CI workflow

- Update the Python version matrix
- Update dependency install commands
- Keep the Guardian step names for consistent branding (or rebrand)

### 6. Set up branch protection

See [branch-protection.md](branch-protection.md) for recommended settings.

## What Not to Copy

- `.agents/` agent definitions (Goblin-specific)
- `config/` TOML policy files (Goblin governance)
- `Goblin/` program control plane
- Experiment and approval directories
