# MT5 Packet: AF-CAND-0263

- Practice only: true
- Canonical research data source: OANDA
- MT5 is parity validation only and must not feed training or research data stores.
- MT5 packet artifacts must not be reused as features, labels, or ranking inputs.
- Primary parity gate: rebuild the executable baseline from MT5-exported broker history captured during the tester run.
- Packet expected signals remain a fallback artifact only when broker history export is unavailable.
- MT5 packet run id: mt5run-20260412T012339Z
- Automated terminal path: data\state\mt5_automation_runtime\terminal64.exe
- Automated terminal data path: data\state\mt5_automation_runtime
- Automated MetaEditor path: data\state\mt5_automation_runtime\MetaEditor64.exe
- Audit output path: <MT5_COMMON_FILES>/AgenticForex\Audit\AF-CAND-0263__mt5run-20260412T012339Z__audit.csv
- Broker history output path: <MT5_COMMON_FILES>/AgenticForex\Audit\AF-CAND-0263__broker_history.csv
- Deployed MQ5 path: data\state\mt5_automation_runtime\MQL5\Experts\AgenticForex\AF-CAND-0263.mq5
- Compiled EX5 path: data\state\mt5_automation_runtime\MQL5\Experts\AgenticForex\AF-CAND-0263.ex5
- Compile log path: unavailable