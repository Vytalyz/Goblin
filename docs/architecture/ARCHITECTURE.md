# Goblin System Architecture

Visual architecture diagrams for the Goblin algorithmic forex research platform.

---

## System Overview

```mermaid
---
title: Goblin System Architecture
---
flowchart TB
    subgraph OPERATOR["AI Operator Layer"]
        direction LR
        CopilotAgent["GitHub Copilot"]
        ClaudeCode["Claude Code"]
        Codex["OpenAI Codex"]
    end

    subgraph CONTROL["Goblin Control Plane"]
        direction LR
        ProgramStatus["Program Status\n& Phase Tracking"]
        Incidents["Incident System\n& SLA Contracts"]
        DeployLadder["Deployment Ladder\n& Bundle Control"]
        RunBooks["Runbooks\n& Recovery"]
    end

    subgraph AGENTS["Agentic Components"]
        direction LR
        AgentDefs["Agent Definitions\n16+ agents"]
        Skills["Skills\n14 skills"]
        Hooks["Hooks\n& Contracts"]
        Registry["Component Registry"]
    end

    subgraph KERNEL["Deterministic Kernel - src/agentic_forex/"]
        direction TB

        subgraph DATA_PIPELINE["Data Pipeline"]
            direction LR
            OANDA["OANDA API\nCanonical Source"]
            Ingest["Market Data\nIngest"]
            Normalize["Normalize\n& QA"]
            Features["Feature\nEngineering"]
            DuckDB[("DuckDB\nStorage")]
        end

        subgraph STRATEGY["Strategy Engine"]
            direction LR
            Backtest["Backtesting\nEngine"]
            StressTest["Stress Test\n& Walk-Forward"]
            Evaluation["Evaluation\n& Grading"]
            ForwardTest["Shadow Forward\nValidation"]
        end

        subgraph GOVERNANCE["Governance Layer"]
            direction LR
            TrialLedger["Trial Ledger\n& Provenance"]
            Approval["Approval\nGates"]
            ControlPlane["Control Plane\nLeases & Events"]
            PolicyEngine["Policy Engine\nTOML Config"]
        end

        subgraph MT5_LAYER["MT5 Parity Pipeline"]
            direction LR
            EAGenerator["EA Code\nGenerator"]
            MT5Packet["MT5 Packet\nBuilder"]
            ParityAudit["Parity Audit\n& Certification"]
        end

        subgraph PORTFOLIO["Portfolio & Program"]
            direction LR
            ProgramLoop["Program Loop\n& Lane Manager"]
            AutonomousMgr["Autonomous\nManager"]
            PortfolioCycle["Portfolio\nCycle"]
            CampaignEngine["Campaign\nEngine"]
        end

        subgraph RUNTIME["Workflow Runtime"]
            direction LR
            WorkflowEngine["Workflow Engine\nJSON Definitions"]
            LLMClient["LLM Client\nProvider-Neutral"]
            ToolRegistry["Tool\nRegistry"]
        end

        subgraph LIVE["Live Demo Observability"]
            direction LR
            LiveAttach["Live Attach\n& Heartbeat"]
            BrokerRecon["Broker\nReconciliation"]
            SignalTrace["Signal\nTrace"]
        end
    end

    subgraph MT5_EXT["MT5 Platform - Practice Only"]
        direction LR
        MT5Terminal["MetaTrader 5\nStrategy Tester"]
        DemoAccount["Demo Account\nEA Execution"]
    end

    subgraph CONFIG["Configuration"]
        direction LR
        DefaultTOML["config/default.toml"]
        DomainTOML["Domain Policy\nTOMLs"]
        LocalTOML["config/local.toml\nGitignored"]
        SecretsMgr["Windows Credential\nManager"]
    end

    %% Operator layer connections
    OPERATOR -->|"orchestration only\nno runtime dependency"| CONTROL
    OPERATOR -->|"invoke skills\n& hooks"| AGENTS

    %% Control plane to kernel
    CONTROL -->|"phase gates\n& contracts"| GOVERNANCE

    %% Agent layer to kernel
    AGENTS -->|"deterministic\ntool calls"| KERNEL

    %% Data pipeline flow
    OANDA --> Ingest --> Normalize --> Features
    Ingest --> DuckDB
    Normalize --> DuckDB

    %% Strategy flow
    Features --> Backtest --> StressTest --> Evaluation
    Features --> ForwardTest

    %% Governance connections
    Backtest --> TrialLedger
    StressTest --> TrialLedger
    Evaluation --> Approval
    ForwardTest --> TrialLedger
    PolicyEngine --> Approval
    Approval --> ControlPlane

    %% MT5 pipeline
    Approval -->|"mt5_packet\nstage"| MT5Packet
    EAGenerator --> MT5Packet
    MT5Packet --> MT5Terminal
    MT5Terminal --> ParityAudit
    ParityAudit --> TrialLedger

    %% Live demo
    ParityAudit -->|"deployment\nbundle"| LiveAttach
    LiveAttach --> DemoAccount
    DemoAccount --> BrokerRecon
    DemoAccount --> SignalTrace

    %% Portfolio orchestration
    ProgramLoop --> CampaignEngine
    CampaignEngine --> AutonomousMgr
    AutonomousMgr --> PortfolioCycle

    %% Config connections
    CONFIG --> PolicyEngine
    SecretsMgr -->|"resolve_secret()"| OANDA

    %% Workflow runtime
    WorkflowEngine --> LLMClient
    WorkflowEngine --> ToolRegistry

    %% Style
    classDef operator fill:#4a90d9,stroke:#2c5f8a,color:#fff
    classDef control fill:#6b8e23,stroke:#4a6319,color:#fff
    classDef agents fill:#9b59b6,stroke:#6c3483,color:#fff
    classDef kernel fill:#2c3e50,stroke:#1a252f,color:#fff
    classDef data fill:#e67e22,stroke:#a35816,color:#fff
    classDef mt5 fill:#c0392b,stroke:#8b2920,color:#fff
    classDef config fill:#7f8c8d,stroke:#5d6d6e,color:#fff

    class CopilotAgent,ClaudeCode,Codex operator
    class ProgramStatus,Incidents,DeployLadder,RunBooks control
    class AgentDefs,Skills,Hooks,Registry agents
    class OANDA,Ingest,Normalize,Features,DuckDB data
    class MT5Terminal,DemoAccount,EAGenerator,MT5Packet,ParityAudit mt5
    class DefaultTOML,DomainTOML,LocalTOML,SecretsMgr config
```

### Layer Descriptions

| Layer | Location | Role |
|-------|----------|------|
| **AI Operator** | External (Copilot, Claude, Codex) | Advisory orchestration — no runtime dependency |
| **Control Plane** | `Goblin/` | Program phases, incidents, deployment bundles, runbooks |
| **Agentic Components** | `.agents/` | Agent definitions, skills, hooks, registry |
| **Deterministic Kernel** | `src/agentic_forex/` | All research, evaluation, governance, and trading logic |
| **Configuration** | `config/` | TOML policy files, local overrides (gitignored), secrets |
| **MT5 Platform** | External | Practice/parity validation only — never research truth |

---

## Strategy Deployment Ladder

Every strategy candidate progresses through governed stages. No stage can be skipped.

```mermaid
---
title: Strategy Deployment Ladder
---
flowchart LR
    Discovery["Discovery\n& Hypothesis"]
    Backtest["Backtest\n& Stress Test"]
    Robustness["Robustness\nReview"]
    Forward["Shadow Forward\nValidation"]
    MT5Parity["MT5 Parity\nCertification"]
    Shadow["Shadow-Only\nDemo Week"]
    LimitedDemo["Limited Demo\nActive Trading"]
    ObservedDemo["Observed Demo\nFull Monitoring"]
    ChallengerDemo["Challenger Demo\nBenchmark Race"]
    Eligible["Eligible for\nReplacement"]

    Discovery --> Backtest --> Robustness --> Forward
    Forward --> MT5Parity --> Shadow --> LimitedDemo
    LimitedDemo --> ObservedDemo --> ChallengerDemo --> Eligible

    classDef research fill:#3498db,stroke:#2471a3,color:#fff
    classDef governance fill:#f39c12,stroke:#d68910,color:#fff
    classDef demo fill:#27ae60,stroke:#1e8449,color:#fff
    classDef final fill:#8e44ad,stroke:#6c3483,color:#fff

    class Discovery,Backtest research
    class Robustness,Forward,MT5Parity governance
    class Shadow,LimitedDemo,ObservedDemo demo
    class ChallengerDemo,Eligible final
```

| Stage | Gate Type | Evidence Required |
|-------|-----------|-------------------|
| Discovery | Automated | Strategy hypothesis + rationale card |
| Backtest | Automated | Trade count, profit factor, expectancy thresholds |
| Robustness | Automated | Walk-forward, stress test, deflated Sharpe |
| Shadow Forward | Automated | Out-of-sample validation on recent OANDA data |
| MT5 Parity | Automated + Human | EA compilation, parity audit, certification report |
| Shadow Demo | Operational | 1-week shadow mode — signals only, zero orders |
| Limited Demo | Operational | Active demo trading with full observability |
| Observed Demo | Operational | Extended monitoring period with broker reconciliation |
| Challenger Demo | Human | Head-to-head vs. locked benchmark |
| Eligible | Human | Final promotion decision with statistical evidence |

---

## Four-Channel Truth Stack

Goblin uses four independent evidence channels. Each adjacent pair has a specific comparison enforcement level.

```mermaid
---
title: Four-Channel Truth Stack
---
flowchart LR
    Research["Research Backtest\nOANDA - Canonical"]
    MT5["MT5 Replay\nPractice Only"]
    LiveDemo["Live Demo\nDemo Account"]
    Broker["Broker Account\nHistory"]

    Research -->|"structural\nconsistency"| MT5
    MT5 -->|"strict executable\nparity"| LiveDemo
    LiveDemo -->|"strict\nreconciliation"| Broker

    classDef canonical fill:#2ecc71,stroke:#1a9c56,color:#fff
    classDef practice fill:#e67e22,stroke:#a35816,color:#fff
    classDef live fill:#e74c3c,stroke:#a33527,color:#fff
    classDef external fill:#9b59b6,stroke:#6c3483,color:#fff

    class Research canonical
    class MT5 practice
    class LiveDemo live
    class Broker external
```

| Channel Pair | Enforcement | Decision Scope |
|-------------|-------------|----------------|
| Research ↔ MT5 | Structural consistency | Research-to-executable validation |
| MT5 ↔ Live Demo | Strict executable parity | Deployment-grade validation |
| Live Demo ↔ Broker | Strict reconciliation | Operational and financial reconciliation |

**Key rule:** MT5 evidence can explain failures but cannot establish promotion truth. OANDA research is the canonical data source.

---

## Directory Map

```
├── .agents/           # Canonical agentic components
│   ├── agents/        #   Agent definitions (16+)
│   ├── skills/        #   Skill definitions (14)
│   ├── hooks/         #   Hook contracts
│   └── registry.json  #   Component registry
├── src/
│   ├── agentic_forex/ # Deterministic kernel (24 subpackages)
│   └── goblin/        # Bridge namespace (sys.modules aliasing)
├── Goblin/            # Program control plane
│   ├── STATUS.md      #   Current phase state
│   ├── contracts/     #   Governance contracts
│   ├── checkpoints/   #   Phase completion evidence
│   └── runbooks/      #   Operational runbooks
├── config/            # TOML policy files
├── workflows/         # JSON workflow definitions
├── approvals/         # Approval log + MT5 packets/runs
├── experiments/       # Trial ledger + campaign data
└── docs/              # Architecture + governance docs
```
