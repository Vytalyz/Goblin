---
name: artifact-audit
description: Audit operator manifests, campaign reports, and candidate artifacts for provenance, integrity, or policy drift. Use when the repo needs a deterministic evidence trail review.
---

# Artifact Audit

Operate on generated reports and traces, not guesswork.

## Workflow

1. Start from the newest operator manifest, campaign report, or candidate artifact.
2. Cross-check report paths, policy hash, and produced artifacts.
3. Escalate mismatches as integrity or policy findings with exact paths.

## Rules

- Prefer concrete file-backed findings over summaries.
- Flag missing or stale artifacts explicitly.
- Do not rewrite artifacts during an audit unless the task is to regenerate them.
