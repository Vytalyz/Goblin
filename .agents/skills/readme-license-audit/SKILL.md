---
name: readme-license-audit
description: Verify the README is complete and clear for external contributors, LICENSE is present and correct, and SECURITY.md exists.
---

# README & License Audit

This skill checks that the repository presents well to external visitors and
meets open-source baseline expectations.

## When to Use

- Before publishing to a public GitHub repository
- When modifying README.md, LICENSE, or SECURITY.md
- During periodic release-readiness checks

## Checklist

### README.md

- [ ] **Project description**: clear one-paragraph explanation of what Goblin is
- [ ] **Highlights or features**: bulleted list of key capabilities
- [ ] **Project structure**: table or tree showing major directories
- [ ] **Requirements**: Python version, OS notes, external dependencies
- [ ] **Install instructions**: `pip install -e ".[dev]"`
- [ ] **Local configuration**: how to set up `.env` and `config/local.toml`
- [ ] **Secrets**: how credentials are resolved (env vars, Credential Manager)
- [ ] **CLI commands**: key `goblin` commands with examples
- [ ] **Tests**: how to run the test suite
- [ ] **Pre-push validation**: how to run the publish-guardian gate
- [ ] **Contributing**: basic contribution workflow and rules
- [ ] **License**: link to LICENSE file
- [ ] **No hardcoded paths**: no `C:\Users\...` in examples (use placeholders)
- [ ] **No internal jargon** without explanation in the opening sections

### LICENSE

- [ ] File exists at repo root
- [ ] Valid recognized license text (MIT, Apache-2.0, etc.)
- [ ] `pyproject.toml` `license` field matches the LICENSE file

### SECURITY.md

- [ ] File exists at repo root
- [ ] Vulnerability reporting instructions
- [ ] Credential hygiene statement
- [ ] Automated trading disclaimer

## Rules

- The publish-validation script checks for LICENSE, SECURITY.md, and README.md existence
- Content quality is a manual review — this skill provides the checklist
