---
name: runtime-monitoring
description: Monitor parity/runtime evidence and queue health after governed runs complete. Use when reviewing MT5 practice logs, operator traces, or blocked automation outcomes.
---

# Runtime Monitoring

Treat runtime evidence as operational telemetry, not research truth.

## Workflow

1. Export operator state or inspect the latest governed action manifest.
2. Review MT5 parity outputs, queue state, and blocked stop reasons.
3. Summarize operational anomalies and route back into governed actions only when policy allows.

## Rules

- Runtime noise never overrides OANDA research evidence.
- Use operator manifests and audit CSVs as primary references.
- Keep hooks optional and out of the critical path.
