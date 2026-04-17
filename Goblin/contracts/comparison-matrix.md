# Comparison Matrix

Use the right comparison contract for the decision being made. Structural consistency is looser than executable parity, and executable parity is looser than broker reconciliation only in scope, not in seriousness.

| Left | Right | Enforcement | Decision Scope |
| --- | --- | --- | --- |
| `research_backtest` | `mt5_replay` | `structural_consistency` | research-to-executable validation |
| `mt5_replay` | `live_demo` | `strict_executable_parity` | deployment-grade validation |
| `live_demo` | `broker_account_history` | `strict_reconciliation` | operational and financial reconciliation |

## Enforcement Notes

- `research_backtest <-> mt5_replay`: structural consistency only. Do not demand identical fills or timestamps.
- `mt5_replay <-> live_demo`: strict executable parity on frozen windows. Missing or extra trades are incident triggers.
- `live_demo <-> broker_account_history`: strict reconciliation. Broker/account evidence is the independent external ledger.
