---
name: candidate-refinement
description: Refine or mutate a governed strategy candidate through bounded next-step or lane execution. Use when a candidate needs a narrow correction, not a fresh family search.
---

# Candidate Refinement

Operate through the governed-action wrapper and candidate artifacts.

## Workflow

1. Read the latest candidate artifacts under `reports/<candidate-id>/`.
2. Confirm the lane is still valid with `queue-snapshot` or `export-operator-state`.
3. Run only bounded governed actions such as `next_step` or `governed_loop`.
4. Inspect the resulting operator manifest and report artifacts before proceeding.

## Rules

- Prefer narrow corrections over broad family resets.
- Stop on explicit HITL, approval, or policy boundaries.
- Do not rescue a candidate by relaxing the deterministic kernel.
