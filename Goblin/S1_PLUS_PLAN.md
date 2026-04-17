# Goblin S1+ Remaining Plan

This document is the authoritative remaining-plan roadmap after Goblin platform phases `GOBLIN-P00` through `GOBLIN-P15` and takeover stages `GOBLIN-T1` through `GOBLIN-T4` are complete.

It exists to answer a different question from `Goblin/ROADMAP.md`:

- `Goblin/ROADMAP.md` explains how Goblin was built.
- `Goblin/S1_PLUS_PLAN.md` explains how the completed Goblin system is used to finish the remaining operational program.

## Planning Objective

The remaining Goblin work is not more control-plane construction. The remaining work is the sequential operating program:

1. operationalize one governed candidate end to end
2. advance that candidate through the deployment ladder to `eligible_for_replacement`
3. use that completed proof to start the next session-scoped strategy lane
4. repeat until the intended session portfolio exists under governed evidence

## Optimization Rule

Sequence work to maximize evidence quality and minimize invalid parallelism.

- Build and advance one strategy at a time.
- Do not begin a new session-window strategy until the current strategy reaches `eligible_for_replacement`.
- Prefer bundling adjacent operational stages into checkpointed blocks so resets, incidents, or pauses do not lose program state.
- Favor earlier work that increases decision quality for later work:
  - attach governance before demo advancement
  - demo advancement before challenger comparison
  - challenger comparison before session expansion
  - session expansion before multi-strategy coordination

## Operator Bootstrap

The stable operator bootstrap for this repo is the CLI command `goblin-startup`.

The workspace prompt `/goblin` is the chat convenience layer for the same startup view.

- `goblin-startup` should work regardless of which model is active, because it is a repo CLI surface rather than a chat-only prompt.
- It should show a Goblin ASCII banner.
- It should summarize the current remaining S1+ plan.
- It should recommend the single best next governed action from current state.
- It should point operators back to this document for the authoritative post-takeover phase sequence.

## Remaining Phase Map

| Remaining Phase | Title | Depends On | Primary Outcome | Checkpoint |
| --- | --- | --- | --- | --- |
| `S1-P01` | Program Bootstrap And Lane Declaration | Goblin platform complete | declare first operational candidate, bundle, lane, and target session scope | `Goblin/checkpoints/S1-P01/` |
| `S1-P02` | Candidate Activation | `S1-P01` | real governed `shadow_only` live-demo run exists | `Goblin/checkpoints/S1-P02/` |
| `S1-P03` | Controlled Demo Advancement | `S1-P02` | candidate reaches `observed_demo` with valid evidence | `Goblin/checkpoints/S1-P03/` |
| `S1-P04` | Challenger Evaluation | `S1-P03` | candidate completes `challenger_demo` against benchmark under equivalent conditions | `Goblin/checkpoints/S1-P04/` |
| `S1-P05` | Replacement Readiness | `S1-P04` | candidate reaches `eligible_for_replacement` with promotion packet and sign-off | `Goblin/checkpoints/S1-P05/` |
| `S1-P06` | Release Decision And Slot Update | `S1-P05` | operator decides replace, retain, or hold; portfolio slot state updated | `Goblin/checkpoints/S1-P06/` |
| `S1-P07` | Next Session Lane Bootstrap | `S1-P06` | next session-window strategy lane is opened under clean-room and rationale controls | `Goblin/checkpoints/S1-P07/` |
| `S1-P08` | Sequential Session Expansion | `S1-P07` | repeat the same governed cycle for each approved session window | `Goblin/checkpoints/S1-P08/` |
| `S1-P09` | Multi-Strategy Coordination Hardening | `S1-P08` once more than one strategy is active | portfolio coordination across sessions is explicitly governed | `Goblin/checkpoints/S1-P09/` |

## Recommended Execution Bundles

The remaining phases should be tracked in four bundles so progress can be reviewed at useful boundaries.

### Bundle A: First Candidate Operationalization

Includes:

- `S1-P01`
- `S1-P02`

Purpose:

- move from readiness to a real governed live-demo object
- prove the first candidate is attachable, observable, and incident-controlled

Definition of done:

- the first candidate is declared with a pinned bundle and session scope
- a real `shadow_only` run exists with attach manifest, heartbeat evidence, runtime summary, and no unresolved blocking incidents

Recommended checkpoint:

- `Goblin/checkpoints/S1-BUNDLE-A/first-candidate-activated.json`

### Bundle B: Ladder Advancement To Decision Readiness

Includes:

- `S1-P03`
- `S1-P04`
- `S1-P05`

Purpose:

- prove the candidate deserves serious replacement consideration
- collect the full body of demo and challenger evidence needed for a governed decision

Definition of done:

- the candidate advances from `limited_demo` to `observed_demo` to `challenger_demo`
- the candidate reaches `eligible_for_replacement`
- a promotion decision packet exists with the required evidence references and operator sign-off

Recommended checkpoint:

- `Goblin/checkpoints/S1-BUNDLE-B/first-candidate-eligible-for-replacement.json`

### Bundle C: First Program Expansion

Includes:

- `S1-P06`
- `S1-P07`

Purpose:

- convert a completed candidate cycle into explicit portfolio state
- start the next session-window lane without losing the governance trail from the first strategy

Definition of done:

- release decision is recorded for the first candidate
- benchmark or incumbent slot state is updated
- the next session-window lane is declared with rationale, clean-room posture, and candidate-governance prerequisites in place

Recommended checkpoint:

- `Goblin/checkpoints/S1-BUNDLE-C/next-session-lane-opened.json`

### Bundle D: Program Scaling

Includes:

- `S1-P08`
- `S1-P09`

Purpose:

- repeat the proven single-strategy cycle until multiple session strategies coexist
- harden portfolio coordination once session overlap becomes a real operational concern

Definition of done:

- at least two session-scoped strategies have completed the governed cycle without bypassing single-strategy sequencing
- portfolio coordination rules are extended from candidate-level governance to active multi-session operation

Recommended checkpoint:

- `Goblin/checkpoints/S1-BUNDLE-D/multi-session-portfolio-governed.json`

## Phase Detail

### `S1-P01`: Program Bootstrap And Lane Declaration

What happens:

- confirm the first target candidate and session scope
- pin the approved deployment bundle and certification evidence
- declare the active benchmark relationship and intended ladder entry
- define what success and rollback mean for the candidate cycle

Done when:

- candidate id, bundle id, benchmark relationship, and target session scope are explicit
- attach prerequisites and incident blockers are checked
- the working plan for the first candidate is frozen in artifacts rather than chat

Primary artifacts:

- candidate stage card
- attach template/checklist
- bundle references

### `S1-P02`: Candidate Activation

What happens:

- perform the first governed `shadow_only` attach
- capture live attach evidence in the `live_demo` channel
- confirm heartbeat and runtime summary writers are functioning for the real attach

Done when:

- a governed `shadow_only` run exists
- attach manifest, heartbeat evidence, and runtime summary exist for the same run id
- no unresolved S1 or S2 incidents block the candidate

Primary artifacts:

- `Goblin/reports/live_demo/<candidate_id>/<run_id>/live_attach_manifest.json`
- `Goblin/reports/live_demo/<candidate_id>/<run_id>/runtime_summary.json`
- `Goblin/reports/live_demo/<candidate_id>/<run_id>/heartbeats/`

### `S1-P03`: Controlled Demo Advancement

What happens:

- advance the candidate to `limited_demo`
- then to `observed_demo` only if transition requirements remain satisfied
- collect broker reconciliation and incident evidence along the way

Done when:

- the candidate has satisfied the `shadow_only -> limited_demo` and `limited_demo -> observed_demo` rules in `Goblin/contracts/deployment-ladder.md`
- no unresolved advancement-blocking incidents remain open

Primary artifacts:

- updated attach manifests per run
- runtime summaries
- broker reconciliation reports
- incident records and closures where needed

### `S1-P04`: Challenger Evaluation

What happens:

- run the candidate in `challenger_demo`
- compare against the benchmark over a declared evaluation window under equivalent conditions

Done when:

- benchmark identity is explicit
- challenger evidence exists for the declared comparison window
- the candidate satisfies the transition requirements into `challenger_demo`

Primary artifacts:

- challenger run records
- benchmark comparison evidence
- promotion-decision support evidence

### `S1-P05`: Replacement Readiness

What happens:

- assemble the promotion packet
- verify no open S1 or S2 incidents remain on benchmark or challenger
- capture operator sign-off for replacement readiness

Done when:

- the candidate reaches `eligible_for_replacement`
- the promotion packet exists with full evidence references
- operator sign-off is recorded

Primary artifacts:

- promotion decision packet
- final challenger evidence bundle
- replacement-readiness checkpoint

### `S1-P06`: Release Decision And Slot Update

What happens:

- decide whether to replace, hold, or continue observing
- update the portfolio slot or benchmark reference explicitly

Done when:

- the program state reflects the governed decision
- replacement or hold rationale is recorded with the evidence references used

Primary artifacts:

- portfolio slot update
- release decision note
- incident references if replacement is deferred

### `S1-P07`: Next Session Lane Bootstrap

What happens:

- select the next approved session-window target
- open the next lane under rationale-card, clean-room, and experiment-accounting controls

Done when:

- the next session lane exists as a governed lane, not just a candidate idea
- rationale, methodology, and portfolio constraints are recorded before search begins

Primary artifacts:

- session lane declaration
- rationale card
- experiment-accounting entry

### `S1-P08`: Sequential Session Expansion

What happens:

- repeat phases `S1-P01` through `S1-P07` for the next approved sessions in order
- preserve one active strategy development cycle at a time

Done when:

- each new session strategy follows the same governed ladder without phase skipping
- session-specific lessons and incidents are captured through run records and investigation artifacts

### `S1-P09`: Multi-Strategy Coordination Hardening

What happens:

- once more than one successful session strategy exists, extend portfolio governance to active coordination across sessions
- govern overlap, conflict, deployment precedence, and benchmark succession across the portfolio

Done when:

- multi-session coordination is explicit in portfolio governance rather than implied by separate single-candidate histories
- the repo can govern multiple active session strategies without reintroducing ambiguity in truth, incidents, or deployment state

## Definition Of Done

Goblin remaining work is complete when all of the following are true:

- the first governed post-takeover candidate has reached `eligible_for_replacement`
- the release decision for that candidate is recorded
- the next session-window lane has been formally opened under governance
- the program can repeat the cycle with checkpoints and no dependency on chat memory

Longer-horizon Goblin program completion is reached when:

- sequential session-window strategies have been completed under the same governed cycle
- portfolio coordination is explicitly governed once multiple strategies coexist

## Immediate Next Recommended Phase

If the user wants to continue the remaining Goblin program now, start with `S1-P01` for the first active candidate and stop at the `Bundle A` checkpoint before moving on.