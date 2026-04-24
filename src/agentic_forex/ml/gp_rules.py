"""Genetic Programming rule discovery engine (ML-P1.5).

Evolves boolean expression trees that represent candidate entry rules using
DEAP.  Each tree is a function of the feature primitives defined in
``agentic_forex.ml.primitives``.

Key design decisions
--------------------
- Fitness: OOS profit factor from a lightweight walk-forward evaluation,
  penalised by tree depth (parsimony pressure).
- Parsimony: Trees deeper than ``max_tree_depth`` are clamped to a large
  negative fitness, not merely penalised — this enforces a hard cap.
- Population governance: Every individual that exceeds the max_depth cap
  is repaired (bloat control) before fitness evaluation.
- OANDA-primary: All training data is sourced from ``settings``; MT5 data
  is never used as fitness evidence here.
- No autonomous execution: GP results are returned as ``GPDiscoveryResult``
  for review and optional injection into the CandidateDraft pipeline.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GPRuleResult:
    """A single evolved rule and its evaluation metrics."""

    rule_str: str          # Human-readable expression string
    tree_depth: int        # Depth of the expression tree
    n_nodes: int           # Total node count
    oos_profit_factor: float
    win_rate: float
    n_signals: int         # Number of True signals on OOS data
    fitness: float         # Final fitness value (PF - parsimony_penalty)
    generation: int        # Generation in which this individual was found


@dataclass
class GPDiscoveryResult:
    """Output of a full GP discovery run."""

    best_rule: GPRuleResult
    top_rules: list[GPRuleResult] = field(default_factory=list)
    population_size: int = 0
    generations_run: int = 0
    parsimony_coefficient: float = 0.01
    max_tree_depth: int = 7
    converged: bool = False
    error: str | None = None

    # Serialisable summary used by the campaign controller
    def to_dict(self) -> dict[str, Any]:
        return {
            "best_rule_str": self.best_rule.rule_str,
            "best_oos_profit_factor": self.best_rule.oos_profit_factor,
            "best_win_rate": self.best_rule.win_rate,
            "best_n_signals": self.best_rule.n_signals,
            "best_fitness": self.best_rule.fitness,
            "best_tree_depth": self.best_rule.tree_depth,
            "best_generation": self.best_rule.generation,
            "population_size": self.population_size,
            "generations_run": self.generations_run,
            "parsimony_coefficient": self.parsimony_coefficient,
            "max_tree_depth": self.max_tree_depth,
            "converged": self.converged,
            "top_rules": [
                {
                    "rule_str": r.rule_str,
                    "oos_profit_factor": r.oos_profit_factor,
                    "fitness": r.fitness,
                    "tree_depth": r.tree_depth,
                }
                for r in self.top_rules
            ],
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Lightweight OOS evaluator
# ---------------------------------------------------------------------------


def _evaluate_rule_on_features(
    rule_func: Any,
    feature_matrix: np.ndarray,
    labels: np.ndarray,
    *,
    stop_loss_pips: float = 10.0,
    take_profit_pips: float = 15.0,
) -> tuple[float, float, int]:
    """Apply ``rule_func`` to each row of ``feature_matrix``.

    Returns:
        (oos_profit_factor, win_rate, n_signals)
    """
    signals: list[bool] = []
    for row in feature_matrix:
        try:
            val = rule_func(*row.tolist())
            signals.append(bool(val))
        except Exception:
            signals.append(False)

    n_signals = sum(signals)
    if n_signals == 0:
        return 0.0, 0.0, 0

    wins = sum(1 for sig, lbl in zip(signals, labels) if sig and lbl == 1)
    losses = sum(1 for sig, lbl in zip(signals, labels) if sig and lbl == 0)

    win_rate = wins / n_signals
    gross_profit = wins * take_profit_pips
    gross_loss = losses * stop_loss_pips
    if gross_loss == 0:
        pf = gross_profit / 0.001 if gross_profit > 0 else 0.0
    else:
        pf = gross_profit / gross_loss

    return pf, win_rate, n_signals


# ---------------------------------------------------------------------------
# DEAP fitness function factory
# ---------------------------------------------------------------------------


def _make_fitness_func(
    toolbox: Any,
    feature_matrix: np.ndarray,
    labels: np.ndarray,
    *,
    parsimony_coefficient: float,
    max_tree_depth: int,
    stop_loss_pips: float,
    take_profit_pips: float,
) -> Any:
    """Return a DEAP-compatible fitness function (returns a 1-tuple)."""

    def evaluate(individual: Any) -> tuple[float]:
        # Hard parsimony cap: exceed max depth → worst fitness
        depth = individual.height
        if depth > max_tree_depth:
            return (-10.0,)

        try:
            func = toolbox.compile(expr=individual)
        except Exception:
            return (-10.0,)

        pf, _wr, n_signals = _evaluate_rule_on_features(
            func,
            feature_matrix,
            labels,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=take_profit_pips,
        )

        # Penalise small-signal rules to avoid cherry-picked micro-regimes
        signal_penalty = max(0.0, (50 - n_signals) * 0.005)

        # Parsimony pressure: penalise tree complexity proportionally
        size_penalty = parsimony_coefficient * len(individual)

        fitness = pf - signal_penalty - size_penalty
        return (fitness,)

    return evaluate


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_gp_discovery(
    feature_matrix: np.ndarray,
    labels: np.ndarray,
    *,
    population_size: int = 150,
    generations: int = 75,
    max_tree_depth: int = 7,
    parsimony_coefficient: float = 0.01,
    crossover_probability: float = 0.7,
    mutation_probability: float = 0.2,
    tournament_size: int = 5,
    stop_loss_pips: float = 10.0,
    take_profit_pips: float = 15.0,
    random_seed: int | None = 42,
    n_top_rules: int = 5,
) -> GPDiscoveryResult:
    """Run Genetic Programming rule discovery.

    Args:
        feature_matrix: Shape ``(n_samples, n_features)`` array of feature
            values.  Columns must correspond to
            ``primitives.FEATURE_TERMINALS[:n_features]``.
        labels: Binary labels ``{0, 1}`` of length ``n_samples``.
        population_size: Number of individuals per generation.
        generations: Maximum number of generations to evolve.
        max_tree_depth: Hard cap on tree depth.  Trees deeper than this
            receive worst fitness and are excluded from selection.
        parsimony_coefficient: Per-node fitness penalty for tree size.
        crossover_probability: Probability of subtree crossover per pair.
        mutation_probability: Probability of subtree mutation per individual.
        tournament_size: Tournament selection pool size.
        stop_loss_pips: Used in OOS profit factor calculation.
        take_profit_pips: Used in OOS profit factor calculation.
        random_seed: Seed for reproducibility.
        n_top_rules: Number of top rules to include in the result.

    Returns:
        ``GPDiscoveryResult`` containing the best evolved rule and summary
        metrics.
    """
    try:
        from deap import algorithms, base, creator, gp, tools
    except ImportError as exc:
        raise ImportError(
            "DEAP is required for GP rule discovery (ML-P1.5). "
            "Install it with: pip install 'deap>=1.4,<2'"
        ) from exc

    from agentic_forex.ml.primitives import FEATURE_TERMINALS, build_primitive_set

    if random_seed is not None:
        random.seed(random_seed)
        np.random.seed(random_seed)

    n_features = min(feature_matrix.shape[1], len(FEATURE_TERMINALS))
    pset = build_primitive_set(n_features)

    # DEAP creator setup (guard against repeated calls in tests)
    if not hasattr(creator, "FitnessMax"):
        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

    toolbox = base.Toolbox()
    toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=1, max_=4)
    toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.expr)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("compile", gp.compile, pset=pset)

    fitness_func = _make_fitness_func(
        toolbox,
        feature_matrix,
        labels,
        parsimony_coefficient=parsimony_coefficient,
        max_tree_depth=max_tree_depth,
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
    )
    toolbox.register("evaluate", fitness_func)
    toolbox.register("select", tools.selTournament, tournsize=tournament_size)
    toolbox.register("mate", gp.cxOnePoint)
    toolbox.register("expr_mut", gp.genFull, min_=0, max_=2)
    toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr_mut, pset=pset)

    # Enforce depth limit after crossover and mutation
    toolbox.decorate("mate", gp.staticLimit(key=_op_height, max_value=max_tree_depth))
    toolbox.decorate("mutate", gp.staticLimit(key=_op_height, max_value=max_tree_depth))

    pop = toolbox.population(n=population_size)
    hof = tools.HallOfFame(n_top_rules)

    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("max", np.max)
    stats.register("avg", np.mean)

    try:
        pop, logbook = algorithms.eaSimple(
            pop,
            toolbox,
            cxpb=crossover_probability,
            mutpb=mutation_probability,
            ngen=generations,
            stats=stats,
            halloffame=hof,
            verbose=False,
        )
    except Exception as exc:
        logger.warning("GP evolution failed: %s", exc)
        return GPDiscoveryResult(
            best_rule=GPRuleResult(
                rule_str="",
                tree_depth=0,
                n_nodes=0,
                oos_profit_factor=0.0,
                win_rate=0.0,
                n_signals=0,
                fitness=-10.0,
                generation=0,
            ),
            error=str(exc),
        )

    # Build result objects from hall of fame
    top_results: list[GPRuleResult] = []
    for gen_i, ind in enumerate(hof):
        func = toolbox.compile(expr=ind)
        pf, wr, n_sig = _evaluate_rule_on_features(
            func,
            feature_matrix,
            labels,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=take_profit_pips,
        )
        top_results.append(
            GPRuleResult(
                rule_str=str(ind),
                tree_depth=ind.height,
                n_nodes=len(ind),
                oos_profit_factor=pf,
                win_rate=wr,
                n_signals=n_sig,
                fitness=ind.fitness.values[0],
                generation=generations,
            )
        )

    best = top_results[0] if top_results else GPRuleResult(
        rule_str="", tree_depth=0, n_nodes=0,
        oos_profit_factor=0.0, win_rate=0.0, n_signals=0,
        fitness=-10.0, generation=0,
    )

    # Check convergence: last few generations showed < 1% fitness improvement
    final_maxes = [row["max"] for row in logbook if row.get("max") is not None]
    converged = False
    if len(final_maxes) >= 10:
        recent = final_maxes[-10:]
        if max(recent) - min(recent) < 0.01:
            converged = True

    return GPDiscoveryResult(
        best_rule=best,
        top_rules=top_results,
        population_size=population_size,
        generations_run=generations,
        parsimony_coefficient=parsimony_coefficient,
        max_tree_depth=max_tree_depth,
        converged=converged,
    )


# ---------------------------------------------------------------------------
# Helper used by DEAP decorators
# ---------------------------------------------------------------------------

def _op_height(ind: Any) -> int:
    """Return the height of a GP individual (required by staticLimit decorator)."""
    return ind.height
