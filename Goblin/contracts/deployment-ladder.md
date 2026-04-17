# Deployment Ladder

This contract defines the required states a candidate must pass through before reaching full live deployment. Bundle approval grants a candidate a valid release identity but does not imply operational readiness. Ladder state and bundle identity are separate concerns and must both be present in any live attach.

## Ladder States

| State | Meaning | Can Place Real Orders |
| --- | --- | --- |
| `shadow_only` | Candidate runs in observation mode only; no orders placed, signals logged only | No |
| `limited_demo` | Candidate runs on demo account with active monitoring; reduced lot sizing or session scope | Demo only |
| `observed_demo` | Candidate runs full-configuration demo; full session scope, full lot sizing, active operator monitoring | Demo only |
| `challenger_demo` | Candidate runs alongside the current benchmark candidate for head-to-head comparison; both must run under equivalent conditions | Demo only |
| `eligible_for_replacement` | Candidate has satisfied all promotion criteria and may replace the benchmark in the next governed release cycle | Demo or live pending release |

## Transition Requirements

### `shadow_only` → `limited_demo`

- Valid release bundle exists (`deployment-bundle.md`)
- MT5 certification at `deployment_grade`
- No open S1 or S2 incidents
- Attach manifest confirmed
- Statistical-policy minimum observation trade count met for the strategy class

### `limited_demo` → `observed_demo`

- All `limited_demo` requirements still satisfied
- Broker reconciliation report exists with status `matched` or `mismatch` with accepted closure
- At least one full session observed without open S2+ incidents
- Runtime summary shows zero `audit_write_failures`
- No unresolved heartbeat anomalies

### `observed_demo` → `challenger_demo`

- All `observed_demo` requirements still satisfied
- Statistical-policy promotion-eligible trade count met
- Variance bands within declared tolerances for the strategy class
- Strategy rationale card exists (see `strategy-rationale-card.md`)
- Benchmark candidate identity declared — challenger cannot advance without knowing what it is challenging

### `challenger_demo` → `eligible_for_replacement`

- Challenger has outperformed or matched benchmark across a declared evaluation window
- No open S1 or S2 incidents on either challenger or benchmark
- Promotion decision packet exists with full evidence references
- Operator sign-off recorded

## Ladder State Invariants

- A candidate may not skip states. Each transition requires evidence for the preceding state.
- A candidate with an open S1 incident is suspended at its current state; ladder state does not advance.
- A candidate with an open S2 incident may remain at its current state but may not advance until the incident is closed or a formal monitoring plan is accepted.
- Ladder state is attached to the release bundle. If a new bundle is issued (EA recompile, config change), the new bundle re-enters at `shadow_only` or `limited_demo` depending on the magnitude of the change, unless the operator explicitly accepts continuation at the current state with documented rationale.

## Bundle Approval vs Ladder State

These are distinct:

- **Bundle approval** (`deployment-bundle.md`): confirms the EA binary, inputs, and assumptions are consistent and the release is governed. Issued by the release pipeline.
- **Ladder state**: reflects operational evidence accumulated over real-execution runs. Advanced by the operator after reviewing evidence.

Holding a valid bundle does not grant any ladder state above `shadow_only`. Ladder advancement requires real-execution evidence.

## Ladder State In Artifacts

- `LiveAttachManifest` must carry the ladder state at time of attach.
- Incident closure packets must carry the ladder state at incident open.
- Promotion decision packets must carry both the current ladder state and the ladder state at the time the evidence was collected.
