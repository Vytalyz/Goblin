# Execution Cost Contract

This contract defines the single declared execution-assumption layer shared across all four truth channels: OANDA research backtest, deterministic Python replay, MT5 replay, and live/demo execution. Any divergence between channels on these assumptions is a reconciliation risk and must be surfaced explicitly, not silently absorbed.

## Retroactive Scope

This contract retroactively governs the execution assumptions made in:
- `GOBLIN-P03`: OANDA research data acquisition (price component, spread model)
- `GOBLIN-P04`: MT5 tester configuration (delay model, commission, tester spread)
- `GOBLIN-P05`: live-demo observability (live fill behaviour, lot rounding)

## Spread Source

| Channel | Spread Source | Rule |
| --- | --- | --- |
| `research_backtest` | OANDA bid/ask mid (`BA` price component) | spread = ask − bid per bar; variable |
| `mt5_replay` | MT5 tester symbol spread setting | fixed or broker-server-class-derived; must be noted in certification report |
| `live_demo` | Live broker quote stream | actual market spread; captured in EA audit |
| `broker_account_history` | Broker-settled fill spread | derived from open/close price difference plus commission |

Spread divergence between `research_backtest` and `mt5_replay` is expected and must be explained in the MT5 certification report, not silently ignored.

## Commission Model

| Channel | Commission Assumed | Notes |
| --- | --- | --- |
| `research_backtest` | none (spread-only model) | commission is implicitly embedded in spread assumption |
| `mt5_replay` | zero commission by default unless MT5 symbol has commission configured | certification report must record commission setting |
| `live_demo` | per broker account type | EA audit must record commission if nonzero |
| `broker_account_history` | broker-settled | appears as separate deal type in MT5 account history export |

A strategy that is profitable only under zero commission and fails under realistic commission is not considered viable. Research thresholds must be achievable under the declared commission model.

## Swap Handling

Swaps (overnight financing costs) apply only to positions held past the broker's swap cut-off time. For intraday strategies with forced flat-by-day rules, swaps are expected to be zero. If swaps appear in broker account history for a candidate that is supposed to be flat intraday, this is an incident trigger (`unexpected_swap_in_audit`).

- Declared policy: `intraday_flat_assumed; swap_should_be_zero`
- If swap charges appear: open incident, do not absorb into PnL as noise

## Slippage and Fill-Delay Assumptions

| Parameter | Research | MT5 Replay | Live |
| --- | --- | --- | --- |
| Slippage | `parity_fill_tolerance_pips` from `eval_gates.toml` (default 0.50 pips) | delay model setting in MT5 tester | actual broker fill |
| Fill delay | `stress_fill_delay_ms` from `eval_gates.toml` (default 500ms) | MT5 tester delay model | actual execution latency |

These values come from `config/eval_gates.toml` and are the authoritative cross-channel comparison basis. If thresholds are changed in `eval_gates.toml`, the execution cost contract must be reviewed for consistency.

## Stop and Target Path Assumptions

- Stops and targets are assumed to be hit at the declared price level (no partial fills, no price improvement).
- If MT5 tester uses a price model that allows stop hunting or requotes, this must be declared in the MT5 certification report.
- The deterministic Python engine uses exact price comparisons. MT5 replay may differ by `parity_price_tolerance_pips` (default 0.30 pips); differences beyond this are a parity failure.

## Lot Rounding

- Research uses exact fractional lot sizes. MT5 and live execution round to the nearest valid lot step (minimum 0.01 lots for most brokers).
- Lot rounding is not a parity failure if within one lot step.
- A candidate whose logic produces lot sizes below the minimum step must handle this in the EA explicitly. Rounding to zero is an EA defect, not a model defect.

## Partial Fill Policy

- Partial fills are not supported. If a broker partially fills an order, the EA is expected to cancel the remainder and audit the fill as a complete trade at the partial fill size.
- If partial fills appear in broker account history, they must be reconciled as a single ticket at the filled volume, and the unfilled remainder must appear as a cancelled order (not a missing trade).

## Divergence Classification

When execution cost divergence is discovered between channels during reconciliation:

| Divergence Type | Classification | Required Action |
| --- | --- | --- |
| Spread wider than declared tolerance | `execution_cost_spread_overrun` | note in truth-alignment report |
| Commission present in live but absent in research | `commission_not_modelled` | incident if material to profitability |
| Unexpected swap charge | `unexpected_swap_in_audit` | incident; investigate position hold time |
| Fill outside price tolerance | `fill_price_outside_tolerance` | parity failure; certification downgrade |
| Lot rounded to zero | `lot_rounding_to_zero` | EA defect; block from promotion |
