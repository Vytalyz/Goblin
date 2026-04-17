---
name: incident-review
description: Review blocked program states, integrity incidents, or failed operator manifests and recommend the narrowest safe recovery path. Use when autonomy stops on a real control boundary.
---

# Incident Review

Treat incidents as control failures first and strategy failures second.

## Workflow

1. Inspect the failing manifest or incident artifact.
2. Identify the exact invariant or policy boundary that stopped progress.
3. Recommend the narrowest safe next step that preserves controls.

## Rules

- Do not bypass the blocked control to keep work moving.
- Distinguish integrity issues from ordinary lane exhaustion.
- Escalate HITL boundaries clearly when manual action is required.
