# Holdout Key Rotation & Loss Policy

## Identity

- **Holdout ID**: `HOLDOUT-ML-P2-20260420`
- **Sealed ciphertext**: `Goblin/holdout/ml_p2_holdout.parquet.enc`
- **Key location**: `~/.goblin/holdout_keys/HOLDOUT-ML-P2-20260420.key` (owner machine; **never** committed)

## Hard Cap

- **2 decryption events maximum** for the entire Phase 2 program.
- Counted from `DEC-ML-HOLDOUT-ACCESS-N-COMPLETED` and `DEC-ML-HOLDOUT-ACCESS-N-ABORTED`
  entries in `Goblin/decisions/ml_decisions.jsonl`.
- Aborted attempts **count toward the cap** (G7).
- Enforcement: `tools/holdout_access_ceremony.py:ceremony_should_refuse`.

## Key Loss Policy

If the Fernet key is lost, corrupted, or otherwise unrecoverable:

1. The sealed holdout ciphertext is **permanently unrecoverable**.
2. **There is no rebuild path.** A regenerated holdout would be a different
   chronological slice of the same dataset, defeating the purpose of pre-commitment.
3. The Phase 2 verdict converts to a **forced NO_GO** at the next gate.
   The reason is documented in a `DEC-ML-2.0-RE-GATE` entry with
   `verdict=no_go` and `rationale=holdout_key_lost_recovery_impossible`.
4. Any subsequent ML phase must begin with a fresh sealing ceremony
   producing a new `HOLDOUT-ML-P{N+1}-{YYYYMMDD}` artifact.

## Rotation Policy

- Keys are **never rotated within a phase**. Rotating a key during the same
  phase would defeat the chronological-pre-commitment property.
- A new key is generated only as part of the next phase's sealing ceremony.
- The old (post-phase) key may be deleted after the phase is closed via
  `DEC-ML-2.0-PHASE-CLOSED`. The ciphertext may be archived for audit.

## Two-Person Rule (Solo-Owner Adaptation)

Because Goblin is operated by a single owner, the conventional two-person
rule is implemented as **time-separated single-person attestation**:

- The midpoint and trigger predictions in `Goblin/decisions/predictions.jsonl`
  must be logged at distinct commit SHAs (R4-11).
- The ceremony workflow `.github/workflows/holdout-ceremony.yml` uses a
  GitHub Environment with required reviewer = the owner; the owner must
  approve the run as a separate human gesture from triggering it.
- Both attestations and the predictions log are signed commits.

## Audit Surface

- `Goblin/decisions/ml_decisions.jsonl` — every INITIATED → COMPLETED/ABORTED chain.
- `Goblin/decisions/predictions.jsonl` — pre-commitment record (R4-11).
- `.github/workflows/ml-phase-gates.yml::holdout-access-audit` — repo-wide static check.
- `.github/workflows/holdout-access.yml` — separate static guard against committed keys.
- `.github/workflows/holdout-ceremony.yml` — manual ceremony invocation.
