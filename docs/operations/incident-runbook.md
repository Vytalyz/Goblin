# Incident Runbook — Architecture Migration

**Generated:** 2026-04-13  
**Phase:** 5 — Operational Resilience  
**Scope:** Architecture migration incidents (not trading incidents — see `Goblin/runbooks/INCIDENT_RESPONSE.md` for those)

---

## Scope

This runbook covers incidents that occur during or after the Goblin architecture migration (Phases 0-6). Trading-related incidents (EA drift, MT5 parity, deployment bundles) are governed by `Goblin/runbooks/INCIDENT_RESPONSE.md`.

---

## Incident Types

### M1 — Test Suite Regression

**Trigger:** `pytest` fails after a migration batch  
**Severity:** Blocking — halt migration  
**Response:**
1. Record: which batch, which test(s), error output
2. `git diff` to identify the change that caused failure
3. Revert the batch: `git checkout -- <affected-paths>`
4. Re-run `pytest` to confirm revert restores green
5. Diagnose root cause before re-attempting
6. Log in decision log (`docs/governance/decision-log.md`)

### M2 — Import Resolution Failure

**Trigger:** `python -m goblin` or `python -m agentic_forex` fails to start  
**Severity:** Blocking — halt migration  
**Response:**
1. Check `src/goblin/__init__.py` bridge aliases — are all 24 packages listed?
2. Check `pyproject.toml` entry points — both `goblin` and `agentic-forex` present?
3. Run `python -c "import goblin; print(goblin.__file__)"` to verify resolution
4. If bridge is broken: `git checkout -- src/goblin/__init__.py`
5. If `pyproject.toml` was modified: `git checkout -- pyproject.toml` + `pip install -e .`

### M3 — Credential Resolution Failure

**Trigger:** OANDA API calls fail after credential target rename  
**Severity:** High — may block research runs  
**Response:**
1. Check `config/default.toml` — are `goblin-practice`/`goblin-live` targets defined?
2. Check secret store — do the new target names exist?
3. If not: add aliases pointing old names → new names (not the reverse)
4. Verify: `goblin export-operator-state --project-root .` succeeds
5. If urgent: revert to `agentic-forex-*` names temporarily

### M4 — Provider Configuration Drift

**Trigger:** Claude Code, Codex, or Copilot stops recognizing agents/skills after migration  
**Severity:** Medium — reduces operator capability  
**Response:**
1. Identify which provider is affected
2. Check provider adapter directory (`.claude/`, `.codex/`, `.vscode/`, `.github/`)
3. Verify canonical files exist in `.agents/`
4. For Codex: check `.codex/agents/*.toml` still loads
5. For Claude: check `.claude/settings.local.json` permissions
6. For Copilot: check `.vscode/mcp.json` parse

### M5 — Registry Integrity Failure

**Trigger:** `.agents/registry.json` references a path that doesn't exist  
**Severity:** Low — informational only until tooling depends on it  
**Response:**
1. Run `goblin registry-sync` (when available) to regenerate
2. Or manually verify paths: `python -c "import json, pathlib; [print(c['canonical_path']) for c in json.load(open('.agents/registry.json'))['components'] if not pathlib.Path(c['canonical_path']).exists()]"`
3. Fix missing paths or remove stale entries

### M6 — Workflow Engine Fails to Load Modified JSON

**Trigger:** Workflow engine crashes or skips nodes after governance field additions  
**Severity:** Blocking — affects runtime  
**Response:**
1. Check if engine uses strict JSON parsing (rejects unknown keys)
2. If strict: revert workflow JSON — `git checkout -- workflows/`
3. Add schema version check to engine to skip unknown fields
4. Re-apply governance fields after engine is tolerant

---

## Escalation Matrix

| Incident | First Responder | Escalation |
|----------|----------------|------------|
| M1 Test Regression | Operator (revert batch) | Root cause before retry |
| M2 Import Failure | Operator (check bridge) | Python packaging expert |
| M3 Credential Failure | Operator (add aliases) | OANDA account admin |
| M4 Provider Drift | Operator (check adapters) | Provider documentation |
| M5 Registry Integrity | Operator (regenerate) | None — low severity |
| M6 Workflow Engine | Operator (revert JSON) | Kernel developer (engine tolerance) |

---

## Post-Incident Checklist

- [ ] Incident type and batch recorded in decision log
- [ ] Root cause documented
- [ ] Corrective action applied and tested
- [ ] Batch re-run successfully
- [ ] Regression test added if gap found
