# Capability Refresh

Use $capability-crawl.

Refresh the repo capability catalog from the configured official Codex/OpenAI pages and repo-local operator surfaces.

Output requirements:
- Run the deterministic capability sync command.
- Summarize any newly failed capability fetches or changed experimental/Windows boundaries.
- If the operator contract is impacted, run the operator contract validator and report findings with file paths.
