---
name: industry-monitoring
description: Generate industry update reports from local corpus, experiment, and pipeline data. Produces Markdown and HTML summaries of the Goblin research platform status.
version: "1.0.0"
inputs:
  - name: project-root
    type: path
    required: false
    description: "Override default project root. Uses config resolution if omitted."
outputs:
  - name: latest.md
    type: path
    description: "Markdown report at reports/industry-update/latest.md"
  - name: latest.html
    type: path
    description: "HTML report at reports/industry-update/latest.html"
requires:
  cli_commands:
    - "goblin industry-report"
  config_files:
    - "config/default.toml"
permissions:
  sandbox: workspace-write
  network: denied
  secrets: []
providers:
  - claude-code
  - openai-codex
  - github-copilot
  - mcp
fallback:
  on_missing_dependency: warn
  degraded_mode: "Report generated with available data; missing sources produce empty sections."
---

# Industry Monitoring

Generate a Goblin Industry Update report summarizing experiment pipeline health, candidate portfolio status, approval activity, corpus coverage, and program status.

## Workflow

1. Run `goblin industry-report --project-root <repo>`.
2. The command scans local data sources (experiments, reports, approvals, corpus, Goblin status).
3. Outputs are written to `reports/industry-update/latest.md` and `reports/industry-update/latest.html`.
4. Review the generated report for accuracy.

## Rules

- No external API calls or web scraping — report uses only local data.
- No AI API key required.
- Report is regenerated fresh each run (not incremental).
- The `reports/industry-update/` directory is created automatically.
