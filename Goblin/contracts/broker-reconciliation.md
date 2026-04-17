# Broker Reconciliation

`broker_account_history` is the reconciliation truth channel. It is the independent external source for what actually happened at the broker/account layer. The EA audit log is self-reported by the EA process; broker account history is external and not controlled by the EA. Reconciliation requires both.

## Channel Position in the Truth Stack

- Compares against `live_demo` under **strict reconciliation**.
- Broker/account history is the final authority on whether a trade was accepted, filled, modified, or rejected by the broker.
- No promotion decision should depend solely on EA audit when broker reconciliation is available.

## Purpose

- Verify that every EA-reported trade appears in broker records.
- Detect broker-side fills, rejections, or modifications not captured in the EA audit.
- Detect PnL discrepancies between EA-computed profit and broker-settled profit.
- Detect execution sequencing anomalies that the EA cannot observe about itself.

## Broker CSV Ingestion Format

The broker reconciliation pipeline accepts a CSV exported from MT5 account history.

Expected column headers (case-insensitive, whitespace-trimmed):

| Column | Required | Description |
| --- | --- | --- |
| `ticket` | yes | MT5 ticket number (unique trade identifier) |
| `symbol` | yes | Instrument traded (e.g., `EURUSD`) |
| `type` | yes | Trade direction (`buy` or `sell`) |
| `volume` | yes | Lot size |
| `open_time` | yes | Trade open timestamp (UTC preferred; offset noted in notes if broker server time) |
| `close_time` | yes | Trade close timestamp |
| `open_price` | yes | Entry fill price |
| `close_price` | yes | Exit fill price |
| `profit` | yes | Broker-settled profit in account currency |

Columns may use spaces instead of underscores (e.g., `Open Time` is normalised to `open_time`). Additional columns are permitted and ignored. The BOM character (`\ufeff`) is stripped if present.

## Matching Algorithm

Trades are matched by **ticket** (primary key). Ticket is the MT5-assigned integer that uniquely identifies a position. It appears in both the EA audit and the broker CSV export.

Matching priority:
1. Exact ticket match: EA audit ticket == broker CSV ticket
2. If no exact match found, the trade is classified as missing or extra (no fuzzy matching)

## Mismatch Classification

| Class | Meaning | Governance Effect |
| --- | --- | --- |
| `matched` | Ticket found in both EA audit and broker history | no incident required if PnL delta is within tolerance |
| `missing_broker_trade` | EA audit has a ticket that broker history does not | incident trigger: `broker_missing_ea_trade` |
| `extra_broker_trade` | Broker history has a ticket not in EA audit | incident trigger: `ea_audit_missing_broker_trade` |
| `pnl_mismatch` | Sum of PnL deltas across matched trades exceeds tolerance | incident trigger: `broker_pnl_mismatch` |

## Reconciliation Status Values

- `not_run`: EA audit not available; broker data was stored but not compared
- `matched`: all trades matched and PnL delta within tolerance
- `mismatch`: one or more mismatches detected

## Report (`BrokerReconciliationReport`)

Written to `Goblin/reports/broker_account_history/<candidate_id>/<run_id>/broker_reconciliation_report.json`.

Required fields:
- `candidate_id`, `account_id`, `broker_source_path`
- `matched_trade_count`
- `missing_broker_trade_count`: EA audit trades not found in broker history
- `extra_broker_trade_count`: broker history trades not found in EA audit
- `cash_pnl_delta`: sum of absolute PnL differences across matched trades
- `reconciliation_status`: one of `not_run`, `matched`, `mismatch`
- `notes`: list of human-readable observations

## Incident Auto-Open Triggers

A reconciliation incident must be opened or kept open when:
- `missing_broker_trade_count > 0`: EA reported trades the broker did not record.
- `extra_broker_trade_count > 0`: Broker recorded trades the EA did not audit.
- `cash_pnl_delta` exceeds the configured tolerance (recommended default: 1.0 account currency units per trade).
- `reconciliation_status = "not_run"` at promotion gate — reconciliation must have run before live evidence is treated as authoritative.

## Separation Rule

- Broker reconciliation artifacts live under `broker_account_history`, not `live_demo`.
- EA audit is `live_demo` channel evidence.
- The reconciliation report is the only artifact that bridges both channels. It must not replace or overwrite either source.

## Broker Time Offset

MT5 broker server time is typically UTC+2 or UTC+3 (DST-dependent). When broker CSVs record timestamps in server time rather than UTC, this must be noted in the reconciliation report's `notes` field and the offset applied before any time-based comparisons.

## MT5 Account History Primitives

MT5 distinguishes several types of records in its account history export. The reconciliation pipeline must treat these separately:

| Primitive | MT5 Type | Reconciliation Handling |
| --- | --- | --- |
| Position close | `deal` with entry `out` | primary trade record; matched against EA audit by ticket |
| Position open | `deal` with entry `in` | paired with close; missing open deal is a provenance warning, not a mismatch |
| Commission charge | `deal` of type `commission` | stored as balance operation; not matched against trade tickets |
| Swap charge | `deal` of type `swap` | checked against `unexpected_swap_in_audit` policy |
| Deposit / withdrawal | `balance` operation | stored separately; must not appear in trade match logic |
| Cancelled order | `order` with state `cancelled` | recorded as context; not a trade mismatch |

The broker CSV export from MT5 account history typically includes all of these as rows. The reconciliation pipeline must filter to position-close deals for trade matching, and store the remainder as balance operations or order context.

## Export Snapshot Cadence

The broker account history export is a point-in-time snapshot. For a single live/demo run:
- Export should be taken after the run is complete and all positions are closed.
- If a run is still active, partial exports are acceptable but must be noted as `partial_snapshot` in the reconciliation report notes field.
- Exporting too early (before all trades settle) may cause false `missing_broker_trade` classifications.

Recommended cadence: one export per run, after confirmed flat position.

## Reconciliation Cadence

- Minimum: once per live/demo run, at run close.
- Before any promotion gate: reconciliation must be current (run against the most recent broker export for the candidate).
- Before ladder state advancement from `observed_demo` to `challenger_demo`: reconciliation status must be `matched` or `mismatch` with accepted closure packet.

## Retention

- Broker CSV files are authoritative artifacts. Once ingested and registered, the original file must not be deleted.
- Reconciliation reports are also authoritative and must be preserved alongside the broker CSV.
