# MT5 Certification

MT5 replay is the executable validation truth for MT5-targeted deployment.

## Certification Artifact

- Canonical artifact: `Goblin/reports/mt5_certification/<candidate_id>/<run_id>/mt5_certification_report.json`
- Every official parity run, diagnostic parity run, and incident replay must emit a Goblin MT5 certification report.
- `MT5ParityReport` and `MT5IncidentReplayReport` must carry the certification status and artifact path.

## Required Metadata

- `tester_mode`
- `delay_model`
- `tick_provenance`
- `symbol_snapshot`
- `account_snapshot`
- `terminal_build`
- `broker_server_class`

## Authority Rules

- No MT5 replay is authoritative unless a Goblin certification artifact exists and resolves to `deployment_grade`.
- Diagnostic parity can explain executable deltas but cannot become authoritative strategy evidence.
- Incident replay can explain a live incident only after the latest known-good baseline harness reproduction passes.
- Launch failures, timeouts, failed parity validation, or missing baseline reproduction force the certification status to `untrusted`.
- Harness trust status must remain separate from candidate alpha quality claims.

## Minimum Certification Conditions

- baseline known-good reproduction passes
- expected trade count is within tolerance
- expected session/hour participation is within tolerance
- entry and exit sequencing is within tolerance
- no unexplained missing or extra trades exist on frozen validation windows

## Deterministic Engine Status

- `deployment_grade`: official parity run completed, validation passed, and the Goblin certification artifact explicitly approves MT5 authority for deployment decisions
- `research_only`: the MT5 run completed with a trusted harness envelope, but the run remains diagnostic or incident-analysis evidence only
- `untrusted`: the MT5 run cannot support authority claims because the harness, launch, or validation envelope failed

## Tick Provenance Rule

- `Every tick based on real ticks` maps to `real_ticks`.
- `1 minute OHLC`, `Open prices only`, and synthetic `Every tick` modes map to `generated_ticks`.
- Unknown tester modes must remain `unknown` until explicitly classified.
