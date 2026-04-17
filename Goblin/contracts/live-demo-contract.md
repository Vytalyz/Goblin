# Live Demo Contract

Live demo is the operational truth channel. It captures what the attached EA actually did in the real trading terminal during a live or demo session. Live-demo truth is independent of research and MT5 replay — it answers a different question: did the EA behave correctly in the live environment?

## Channel Position in the Truth Stack

- Compares against `mt5_replay` under **strict executable parity** (MT5 vs live).
- Compares against `broker_account_history` under **strict reconciliation** (live vs broker).
- Live demo is NOT self-validating. Its audit files are written by the EA itself. External reconciliation via broker/account history is required to independently verify what happened.

## Required Artifacts Per Run

Every governed live or demo run must produce the following artifacts under `Goblin/reports/live_demo/<candidate_id>/<run_id>/`:

| Artifact | File | Required |
| --- | --- | --- |
| Attach manifest | `live_attach_manifest.json` | yes |
| Runtime summary | `runtime_summary.json` | yes |
| Heartbeat series | `heartbeats/heartbeat_<timestamp>.json` | at least one |
| EA audit log | `ea_audit.json` | yes (written by EA) |
| Inputs hash | captured in attach manifest | yes |

## Attach Manifest (`LiveAttachManifest`)

Captures the EA configuration at the moment of attachment. Must be written before any trades execute.

Required fields:
- `candidate_id`: identifies the strategy under test
- `run_id`: unique per attach session
- `account_id`: MT5 account number (demo or live)
- `chart_symbol`: symbol the EA is attached to
- `timeframe`: chart timeframe string
- `leverage`: account leverage at attach time
- `lot_mode`: how position sizing was configured
- `terminal_build`: MT5 build number at attach time
- `attached_utc`: UTC timestamp of attachment
- `attachment_confirmed`: boolean — operator has verified EA loaded without errors
- `inputs_hash`: SHA-256 of the `.set` file used for this attach

## Runtime Summary (`RuntimeSummary`)

Aggregates per-run operational metrics. Must be written at run end or on controlled shutdown.

Required fields:
- `candidate_id`, `run_id`, `generated_utc`
- `bars_processed`: total bars the EA processed
- `allowed_hour_bars`: bars passing session/hour filter
- `filter_blocks`: bars blocked by non-time filters
- `spread_blocks`: bars blocked by spread guard
- `signals_generated`: signals that passed all filters
- `order_attempts`: total order placement attempts
- `order_successes`: placements confirmed by broker
- `order_failures`: placements that errored or were rejected
- `audit_write_failures`: EA-side failures writing audit rows

## Heartbeat (`RuntimeHeartbeat`)

Periodic health snapshot written at a configurable interval (recommended: every 15–30 minutes of market time). Used to detect environment drift mid-session.

Required fields:
- `candidate_id`, `run_id`, `timestamp_utc`
- `status`: one of `healthy`, `warning`, `stale`, `offline`
- `terminal_active`: whether the MT5 terminal process is responsive
- `algo_trading_enabled`: whether MT5 algo trading flag is on
- `account_changed`: whether the active account has changed since attach
- `stale_audit_detected`: whether the EA audit file has not updated within the expected interval

## EA Audit Log (`ea_audit.json`)

Written by the EA itself. Treated as self-reported evidence — it is NOT the external truth. The Goblin broker reconciliation pipeline compares EA audit against the broker account history to produce independent verification.

Expected format:
```json
{
  "candidate_id": "AF-CAND-XXXX",
  "run_id": "live-run-YYYYMMDD",
  "trades": [
    {
      "ticket": "12345678",
      "symbol": "EURUSD",
      "trade_type": "buy",
      "volume": 0.01,
      "open_time": "2026-01-15T09:30:00Z",
      "close_time": "2026-01-15T11:00:00Z",
      "open_price": 1.10500,
      "close_price": 1.10700,
      "profit": 2.00
    }
  ]
}
```

Fields `ticket`, `symbol`, `trade_type`, `open_time`, and `close_time` are required per trade row.

## Chaos and Failure Scenarios

The following runtime failures must be detectable via heartbeat anomaly detection and must trigger an incident if unresolved:

| Scenario | Detection | Required Response |
| --- | --- | --- |
| Terminal closed mid-session | `terminal_active = false` in heartbeat | open incident `terminal_close_mid_session` |
| Sleep/wake cycle detected | heartbeat gap > configured stale threshold | open incident `heartbeat_gap_sleep_wake` |
| Account changed | `account_changed = true` in heartbeat | open incident `account_identity_change`, halt new orders |
| Algo trading disabled | `algo_trading_enabled = false` in heartbeat | open incident `algo_trading_disabled`, note missed signals |
| Stale audit file | `stale_audit_detected = true` | open incident `ea_audit_write_failure` |
| Attach without manifest | `live_attach_manifest.json` missing | run is not a governed run; treat evidence as unregistered |

## Incident Auto-Open Triggers

An incident must be opened automatically (or flagged for operator review) when:
- Any heartbeat anomaly is detected and not resolved within the same session.
- `audit_write_failures > 0` in the runtime summary.
- `order_failures > 0` without a corresponding resolved incident.
- `attachment_confirmed = false` at run close (attach was never verified).
- EA audit is missing at run close.

## Live-Demo Authority Rules

- Live demo evidence is authoritative for operational behavior questions.
- It is NOT authoritative for alpha claims — alpha remains owned by `research_backtest`.
- Live demo evidence that was collected without an attach manifest is **unregistered** and must not be used to support promotion decisions.
- Any live demo run that produced an unresolved incident retains incident-open status until the closure packet is accepted.

## Timezone and Time Basis

- All timestamps in live-demo artifacts must be stored in UTC.
- Heartbeat and attach manifests must include the timestamp at write time (not broker server time).
- Broker server time offsets are captured in the broker reconciliation pipeline, not here.
