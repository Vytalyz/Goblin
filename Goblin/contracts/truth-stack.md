# Truth Stack

Goblin uses a four-channel decision-specific truth stack:

- `research_backtest`: research truth
- `mt5_replay`: executable validation truth
- `live_demo`: operational truth
- `broker_account_history`: reconciliation truth

No single channel is globally authoritative for every decision. Each channel answers a specific question, and each comparison pair uses the contract appropriate to that question.

## Channel Questions

- `research_backtest`: is there a plausible edge worth studying?
- `mt5_replay`: does the MT5 implementation behave credibly enough to deploy in MT5?
- `live_demo`: did the attached EA behave correctly in the real runtime environment?
- `broker_account_history`: what actually happened externally at the broker/account layer?
