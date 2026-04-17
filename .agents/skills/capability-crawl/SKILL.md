---
name: capability-crawl
description: Sync the official Codex/OpenAI capability surface and repo-local operator surfaces into the repo capability catalog. Use before operator-architecture changes, operator validation, or automation design.
---

# Capability Crawl

Use the deterministic capability sync surface instead of hand-maintaining capability docs.

## Workflow

1. Run `goblin sync-codex-capabilities --project-root <repo>`.
2. Inspect `knowledge/codex_capability_catalog.json` and `knowledge/codex_capability_index.md`.
3. Use `goblin validate-operator-contract --project-root <repo>` if the new capability data changes operator assumptions.

## Rules

- Treat official Codex/OpenAI docs as authoritative for Codex capability claims.
- Treat hooks as non-critical and Windows-disabled for this repo.
- Do not hand-edit generated capability catalog files unless the sync path itself is broken.
