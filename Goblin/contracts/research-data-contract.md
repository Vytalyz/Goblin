# Research Data Contract

The OANDA-based research contract must freeze:

- `instrument`
- `price_component`
- `granularity`
- `smooth`
- `include_first`
- `daily_alignment`
- `alignment_timezone`
- `weekly_alignment`
- `utc_normalization_policy`

## Usage

- OANDA remains the canonical research source.
- Research artifacts are valid only when the acquisition configuration is frozen and recorded.
- OANDA ingest and backfill outputs must record the frozen acquisition contract inside their provenance payloads.
- Research truth must not be asked to prove the same thing as MT5 executable validation.
