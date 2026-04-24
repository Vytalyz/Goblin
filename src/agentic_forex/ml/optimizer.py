"""CMA-ES / DE parameter optimizer for governed strategy search (ML-P1.3).

Optimizes numeric strategy parameters (stop_loss_pips, take_profit_pips,
signal_threshold, holding_bars) using Covariance Matrix Adaptation Evolution
Strategy.  Each individual is evaluated through the deterministic backtest
engine with purged walk-forward CV, and PBO score penalises the fitness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cma
import numpy as np

from agentic_forex.backtesting.engine import run_backtest
from agentic_forex.backtesting.models import BacktestArtifact
from agentic_forex.config import Settings
from agentic_forex.workflows.contracts import StrategySpec

logger = logging.getLogger(__name__)

# Parameter names in the order they appear in the CMA-ES vector.
PARAM_NAMES: list[str] = [
    "stop_loss_pips",
    "take_profit_pips",
    "signal_threshold",
    "holding_bars",
]


@dataclass(slots=True)
class OptimizerBounds:
    stop_loss_pips: tuple[float, float] = (5.0, 50.0)
    take_profit_pips: tuple[float, float] = (5.0, 100.0)
    signal_threshold: tuple[float, float] = (0.3, 0.9)
    holding_bars: tuple[int, int] = (5, 120)

    def lower(self) -> list[float]:
        return [
            self.stop_loss_pips[0],
            self.take_profit_pips[0],
            self.signal_threshold[0],
            float(self.holding_bars[0]),
        ]

    def upper(self) -> list[float]:
        return [
            self.stop_loss_pips[1],
            self.take_profit_pips[1],
            self.signal_threshold[1],
            float(self.holding_bars[1]),
        ]

    def midpoint(self) -> list[float]:
        return [(lo + hi) / 2 for lo, hi in zip(self.lower(), self.upper())]


@dataclass(slots=True)
class OptimizerResult:
    best_params: dict[str, float]
    best_fitness: float
    generations_run: int
    evaluations: int
    history: list[dict[str, Any]] = field(default_factory=list)


def _decode_individual(x: np.ndarray, bounds: OptimizerBounds) -> dict[str, float]:
    """Clip the raw CMA-ES vector to bounds and round integer params."""
    lo = bounds.lower()
    hi = bounds.upper()
    clipped = np.clip(x, lo, hi)
    return {
        "stop_loss_pips": round(float(clipped[0]), 1),
        "take_profit_pips": round(float(clipped[1]), 1),
        "signal_threshold": round(float(clipped[2]), 2),
        "holding_bars": int(round(clipped[3])),
    }


def _apply_params_to_spec(spec: StrategySpec, params: dict[str, float]) -> StrategySpec:
    """Return a shallow copy of *spec* with the optimized parameters replaced."""
    data = spec.model_dump(mode="python")
    data["stop_loss_pips"] = params["stop_loss_pips"]
    data["take_profit_pips"] = params["take_profit_pips"]
    data["signal_threshold"] = params["signal_threshold"]
    data["holding_bars"] = params["holding_bars"]
    return StrategySpec.model_validate(data)


def _evaluate_fitness(
    spec: StrategySpec,
    settings: Settings,
    *,
    pbo_penalty_weight: float = 0.3,
) -> float:
    """Evaluate an individual: OOS profit factor penalised by PBO.

    Returns a *negative* fitness (CMA-ES minimises).  Lower = better.
    """
    try:
        artifact: BacktestArtifact = run_backtest(spec, settings, output_prefix="eva_opt")
    except Exception:
        logger.debug("Backtest failed for params — returning worst fitness")
        return 1e6

    oos_pf = artifact.out_of_sample_profit_factor
    if oos_pf <= 0 or artifact.trade_count < settings.validation.minimum_test_trade_count:
        return 1e6

    # PBO penalty: higher PBO → worse fitness.
    # Walk-forward windows provide a quick proxy when CSCV is too expensive
    # per individual.
    wf_penalty = 0.0
    if artifact.walk_forward_summary:
        failing_windows = sum(
            1
            for w in artifact.walk_forward_summary
            if w.get("profit_factor", 0) < settings.validation.walk_forward_profit_factor_floor
        )
        wf_penalty = failing_windows * pbo_penalty_weight

    # Minimise negative OOS PF (so higher PF = lower objective).
    return -(oos_pf - wf_penalty)


def run_cma_optimizer(
    spec: StrategySpec,
    settings: Settings,
    *,
    bounds: OptimizerBounds | None = None,
    population_size: int | None = None,
    max_generations: int | None = None,
    pbo_penalty_weight: float | None = None,
) -> OptimizerResult:
    """Run CMA-ES to optimise strategy parameters.

    Parameters fall back to ``settings.eva_optimizer`` when not supplied.
    """
    eva_cfg = settings.eva_optimizer
    if bounds is None:
        bounds = OptimizerBounds(
            stop_loss_pips=tuple(eva_cfg.stop_loss_pips_bounds),  # type: ignore[arg-type]
            take_profit_pips=tuple(eva_cfg.take_profit_pips_bounds),  # type: ignore[arg-type]
            signal_threshold=tuple(eva_cfg.signal_threshold_bounds),  # type: ignore[arg-type]
            holding_bars=tuple(int(v) for v in eva_cfg.holding_bars_bounds),  # type: ignore[arg-type]
        )
    pop_size = population_size or eva_cfg.default_population_size
    max_gens = max_generations or eva_cfg.default_generations
    penalty_w = pbo_penalty_weight if pbo_penalty_weight is not None else eva_cfg.fitness_pbo_penalty_weight

    x0 = bounds.midpoint()
    sigma0 = max((hi - lo) / 4 for lo, hi in zip(bounds.lower(), bounds.upper()))

    opts = cma.CMAOptions()
    opts["bounds"] = [bounds.lower(), bounds.upper()]
    opts["popsize"] = pop_size
    opts["maxiter"] = max_gens
    opts["verbose"] = -9  # suppress stdout
    opts["seed"] = 42

    es = cma.CMAEvolutionStrategy(x0, sigma0, opts)

    history: list[dict[str, Any]] = []
    gen = 0

    while not es.stop():
        solutions = es.ask()
        fitnesses = []
        for sol in solutions:
            params = _decode_individual(sol, bounds)
            trial_spec = _apply_params_to_spec(spec, params)
            f = _evaluate_fitness(trial_spec, settings, pbo_penalty_weight=penalty_w)
            fitnesses.append(f)
        es.tell(solutions, fitnesses)
        gen += 1

        best_idx = int(np.argmin(fitnesses))
        best_gen_params = _decode_individual(solutions[best_idx], bounds)
        history.append(
            {
                "generation": gen,
                "best_fitness": float(fitnesses[best_idx]),
                "best_params": best_gen_params,
                "mean_fitness": float(np.mean(fitnesses)),
            }
        )
        logger.info("EvA gen %d: best=%.4f mean=%.4f", gen, fitnesses[best_idx], np.mean(fitnesses))

    best_x = es.result.xbest
    best_params = _decode_individual(best_x, bounds)
    best_fitness = float(es.result.fbest)

    return OptimizerResult(
        best_params=best_params,
        best_fitness=best_fitness,
        generations_run=gen,
        evaluations=int(es.result.evaluations),
        history=history,
    )
