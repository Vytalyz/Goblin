"""Phase 1.6.0 — Variance Pilot driver.

Runs the variance pilot (``agentic_forex.ml.variance_pilot``) against real
OANDA research data for a pre-registered set of candidates and seeds.

The script is deliberately standalone (not a `goblin ml` subcommand yet)
so the without-torch CI lane can import it directly and assert that no
torch module is transitively pulled in.

Usage::

    python scripts/run_ml_variance_pilot.py \\
        --candidates AF-CAND-0278 AF-CAND-0375 AF-CAND-0700 \\
        --seeds 0 1 2 3 4 5 6 7 8 9 \\
        --output Goblin/reports/ml/p1_6_0_variance_pilot.json

See ``memories/session/plan.md`` §4 for the acceptance criteria.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# IMPORTANT: do not import torch here. Phase 1.6.0 stays on the without-
# torch CI lane. The guard below fails fast if any transitive import
# pulled torch in before we start the pilot.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_spec(candidate_id: str) -> dict:
    spec_path = REPO_ROOT / "reports" / candidate_id / "strategy_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"strategy_spec.json missing for {candidate_id}: {spec_path}")
    return json.loads(spec_path.read_text(encoding="utf-8"))


def _build_dataset(spec: dict, parquet_path: Path) -> pd.DataFrame:
    from agentic_forex.features.service import build_features
    from agentic_forex.labels.service import build_labels

    frame = pd.read_parquet(parquet_path)
    return (
        build_labels(
            build_features(frame),
            holding_bars=int(spec["holding_bars"]),
            stop_loss_pips=float(spec["stop_loss_pips"]),
            take_profit_pips=float(spec["take_profit_pips"]),
        )
        .dropna()
        .reset_index(drop=True)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1.6.0 variance pilot")
    parser.add_argument(
        "--candidates",
        nargs="+",
        required=True,
        help="Pre-registered candidate IDs (AF-CAND-XXXX); must exclude AF-CAND-0263.",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=list(range(10)),
        help="Random seeds (default: 0..9 for n_seeds=10).",
    )
    parser.add_argument(
        "--parquet",
        type=Path,
        default=REPO_ROOT / "data" / "normalized" / "research" / "eur_usd_m1.parquet",
        help="Path to the normalized research parquet.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "Goblin" / "reports" / "ml" / "p1_6_0_variance_pilot.json",
        help="Output report path.",
    )
    parser.add_argument(
        "--pilot-id",
        default=None,
        help="Override pilot_id (default: derived from UTC timestamp).",
    )
    parser.add_argument(
        "--n-folds",
        type=int,
        default=3,
        help="Walk-forward fold count (inherits train.py default).",
    )
    parser.add_argument(
        "--embargo-bars",
        type=int,
        default=10,
        help="Embargo bar count (inherits train.py default).",
    )
    args = parser.parse_args(argv)

    # Hard guard: refuse to run against the locked benchmark.
    if "AF-CAND-0263" in args.candidates:
        raise SystemExit(
            "AF-CAND-0263 is the locked overlap benchmark and cannot be used in the variance pilot (AGENTS.md)."
        )

    # Import after CLI parse so --help works without installing deps.
    from agentic_forex.governance.models import (
        VariancePilotCandidateResult,
        VariancePilotReport,
    )
    from agentic_forex.ml.variance_pilot import (
        LOCKED_XGB_HPARAMS,
        assert_no_torch_import,
        run_seed,
        summarise,
    )

    parquet = args.parquet.resolve()
    dataset_sha = _sha256(parquet)

    # Feature columns shared with train.py; imported lazily to keep the
    # without-torch import footprint small.
    from agentic_forex.ml.train import FEATURE_COLUMNS

    all_outcomes = []
    per_candidate: dict[str, list] = {cid: [] for cid in args.candidates}
    feature_cols_used: list[str] = []

    for candidate_id in args.candidates:
        spec = _load_spec(candidate_id)
        dataset = _build_dataset(spec, parquet)
        feature_cols = [c for c in FEATURE_COLUMNS if c in dataset.columns]
        # long_outcome_pips is produced by build_labels and holds the
        # signed realized PnL per bar for a long entry at that bar.
        outcome_col = "long_outcome_pips"
        if outcome_col not in dataset.columns:
            raise RuntimeError(f"{candidate_id}: dataset missing '{outcome_col}' — label builder must supply it.")
        feature_cols_used = feature_cols

        for seed in args.seeds:
            outcome = run_seed(
                dataset,
                feature_cols=feature_cols,
                label_col="label_up",
                outcome_col=outcome_col,
                candidate_id=candidate_id,
                seed=int(seed),
                n_folds=args.n_folds,
                embargo_bars=args.embargo_bars,
            )
            all_outcomes.append(outcome)
            per_candidate[candidate_id].append(outcome)
            print(
                f"[pilot] {candidate_id} seed={seed} "
                f"PF={outcome.aggregate_profit_factor:.4f} "
                f"trades={outcome.trade_count}",
                flush=True,
            )

    summary = summarise(all_outcomes)

    candidate_results = []
    for cid, outs in per_candidate.items():
        pfs = np.array([o.aggregate_profit_factor for o in outs], dtype="float64")
        candidate_results.append(
            VariancePilotCandidateResult(
                candidate_id=cid,
                seeds=[o.seed for o in outs],
                profit_factors=[float(p) for p in pfs],
                trade_counts=[o.trade_count for o in outs],
                sigma_pf_within_candidate=float(pfs.std(ddof=1)) if pfs.size > 1 else 0.0,
                mean_pf_within_candidate=float(pfs.mean()),
            )
        )

    pilot_id = args.pilot_id or f"PILOT-1.6.0-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    torch_leaked = "torch" in sys.modules

    report = VariancePilotReport(
        pilot_id=pilot_id,
        dataset_path=str(parquet.relative_to(REPO_ROOT)).replace("\\", "/"),
        dataset_sha256=dataset_sha,
        candidate_ids=list(args.candidates),
        seeds=list(args.seeds),
        n_folds=args.n_folds,
        embargo_bars=args.embargo_bars,
        feature_columns=feature_cols_used,
        locked_xgb_hparams=dict(LOCKED_XGB_HPARAMS),
        candidate_results=candidate_results,
        sigma_pf=summary.sigma_pf,
        mean_pf=summary.mean_pf,
        mde_pf=summary.mde_pf,
        effect_size_floor_pf=summary.effect_size_floor_pf,
        required_n_candidates=summary.required_n_candidates,
        torch_imported_during_run=torch_leaked,
        notes=[
            "MDE and effect-size floor default to 1x sigma_pf; adjust via --mde-multiplier if power analysis indicates.",
            "Downstream phases (1.6, 1.6b, 2.x) must read effect_size_floor_pf from config/eval_gates.toml after operator copies it in.",
        ],
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    # Guard runs last so a leak anywhere in the import graph is caught.
    assert_no_torch_import()
    print(f"[pilot] wrote {args.output}")
    print(
        f"[pilot] sigma_pf={summary.sigma_pf:.4f} "
        f"mean_pf={summary.mean_pf:.4f} "
        f"required_n={summary.required_n_candidates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
