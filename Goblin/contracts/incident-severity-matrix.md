# Incident Severity Matrix

This contract defines the severity levels for Goblin incidents, the automatic suspension rules tied to each level, and the required evidence for closure. Severity is assigned at incident-open time and may be escalated but not downgraded without an explicit operator decision and documented rationale.

## Severity Levels

| Level | Name | Definition |
| --- | --- | --- |
| `S1` | Critical | Incident that prevents live execution from being trustworthy. Immediate suspension required. |
| `S2` | Major | Incident that materially compromises evidence quality or execution integrity but does not require immediate halt. |
| `S3` | Minor | Incident that must be tracked and resolved before promotion but does not block active monitoring. |
| `S4` | Observation | Variance or anomaly within expected bounds but worth recording. Does not block any decision. |

## Incident Type Classification

| Incident Type | Default Severity | Notes |
| --- | --- | --- |
| `provenance_failure` | `S2` | Escalates to S1 if artifact is authoritative and was used in a promotion decision |
| `stale_heartbeat` | `S3` | Escalates to S2 if terminal was offline during a market session |
| `parity_missing_trade` | `S2` | Escalates to S1 if missing trade count > 10% of expected count |
| `parity_extra_trade` | `S2` | Escalates to S1 if extra trade count > 10% of expected count |
| `parity_timing_deviation` | `S3` | Escalates to S2 if deviation exceeds 5 × tolerance threshold |
| `parity_price_deviation` | `S3` | Escalates to S2 if deviation exceeds 5 × pip tolerance |
| `parity_match_rate_failure` | `S1` | Match rate below floor always critical; replay evidence is untrustworthy |
| `live_loss_ordinary_variance_exceeded` | `S3` | Escalates to S2 if breach persists across two consecutive observation windows |
| `live_loss_with_clean_parity` | `S2` | Strategy is losing but execution is correct; requires regime investigation |
| `broker_pnl_mismatch` | `S2` | Escalates to S1 if cash delta > 5× single-trade average profit |
| `broker_missing_ea_trade` | `S2` | EA reported trades broker never recorded |
| `ea_audit_missing_broker_trade` | `S2` | Broker filled trades EA never recorded |
| `account_identity_change` | `S1` | Trading on wrong account is always critical |
| `algo_trading_disabled` | `S2` | Execution capability lost mid-session |
| `terminal_close_mid_session` | `S2` | Escalates to S1 if positions were open at terminal close |
| `ea_audit_write_failure` | `S2` | Evidence integrity compromised |
| `unexpected_swap_in_audit` | `S3` | Position held past cut-off for intraday strategy |
| `commission_not_modelled` | `S3` | Escalates to S2 if commission materially affects profitability claim |
| `release_integrity_failure` | `S1` | Deployed artifact does not match approved bundle |
| `lot_rounding_to_zero` | `S2` | EA defect blocking position sizing |

## Suspension Rules By Severity

| Severity | Automatic Suspension | Manual Override Allowed |
| --- | --- | --- |
| `S1` | Halt new order placement immediately. Existing positions may remain open for managed exit. | Yes, with documented operator rationale and accepted closure plan. |
| `S2` | Halt new order placement at end of current session. Do not proceed to next attach. | Yes, if incident is formally acknowledged and monitoring plan is documented. |
| `S3` | No automatic suspension. Monitor. Must be resolved before next promotion gate. | Not applicable; no suspension to override. |
| `S4` | No action. Record and archive. | Not applicable. |

## Exposure Controls During Incident

When an S1 or S2 incident is open:
- No new live attach is permitted unless the incident is closed or a formal override is accepted.
- No promotion decision may cite live evidence collected after incident open without an accepted closure or monitoring rationale.
- The deployment ladder state must not advance while an unresolved S1 or S2 incident is open (see `deployment-ladder.md`).

## Required Closure Evidence By Severity

| Severity | Minimum Closure Evidence |
| --- | --- |
| `S1` | root-cause document, corrective action proof, verification replay or live run post-fix, operator sign-off |
| `S2` | root-cause summary, corrective action (or accepted monitoring plan), operator sign-off |
| `S3` | root-cause note, resolution date, operator acknowledgement |
| `S4` | no formal closure required; marked resolved automatically after observation window passes |

## Candidate Inheritance

When a candidate inherits a validation stack from another candidate (e.g. derived strategies, challenger variants):
- If the source candidate has an open S1 incident, all inheritors are blocked from new live attach until the S1 closes.
- S2 incidents on the source require the inheritor's operator to acknowledge the shared risk before new attaches proceed.
- S3 and S4 incidents on the source do not block inheritors.
