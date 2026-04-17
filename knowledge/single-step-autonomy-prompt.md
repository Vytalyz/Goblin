# Single-Step Autonomy Prompt Template

Use this template when you want `Agentic Forex` work to be more autonomous without allowing scope drift:

```text
Continue from the latest completed campaign state.

Follow AGENTS.md exactly.

If the latest completed campaign contains explicit next recommendations, treat them as binding unless they conflict with AGENTS.md, readiness gates, artifact requirements, or budget constraints.

Before doing any work:
1. Inspect the latest completed campaign state, trial ledger, candidate artifacts, and current readiness statuses.
2. If that campaign is already completed, open one new bounded child campaign for the next step and persist CampaignSpec and CampaignState before executing candidate work.
3. Select exactly one legal next-step type from this set:
   - diagnose_existing_candidates
   - mutate_one_candidate
   - re_evaluate_one_candidate
   - run_parity
   - run_forward
4. Briefly state why that step is the highest-priority legal next step.
5. Execute only that one step.
6. Validate artifacts, ledger entries, provenance, and readiness.
7. Stop and report. Do not continue into another step.
```

Current runtime support:

- `run-next-step` exists as the repo-level single-step controller entrypoint.
- The currently implemented governed step types are:
  - `diagnose_existing_candidates`
  - `mutate_one_candidate`
  - `re_evaluate_one_candidate`
- Unsupported binding recommendations should stop the run rather than being silently reinterpreted.
