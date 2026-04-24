"""Tests for ML-P1.5 components: GP primitive set and rule discovery engine."""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feature_matrix(n: int = 200, *, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, y) arrays for GP fitness evaluation."""
    rng = np.random.RandomState(seed)
    from agentic_forex.ml.primitives import FEATURE_TERMINALS

    X = rng.randn(n, len(FEATURE_TERMINALS))
    y = (rng.uniform(size=n) > 0.5).astype(int)
    return X.astype(float), y


# ---------------------------------------------------------------------------
# P1.5.2 — Primitive set
# ---------------------------------------------------------------------------


class TestPrimitiveSet:
    def test_feature_terminals_nonempty(self):
        from agentic_forex.ml.primitives import FEATURE_TERMINALS

        assert len(FEATURE_TERMINALS) >= 10

    def test_no_conflation_with_ea(self):
        """Terminal names must not be the literal string 'ea' (avoid EvA/EA conflation)."""
        from agentic_forex.ml.primitives import FEATURE_TERMINALS

        for name in FEATURE_TERMINALS:
            # Check for whole-word "ea" only (not as substring of longer words)
            assert name.lower() != "ea", f"Terminal named '{name}' would cause EvA/EA conflation"

    def test_build_primitive_set_returns_pset(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.primitives import build_primitive_set

        pset = build_primitive_set()
        assert pset is not None

    def test_pset_has_expected_arity(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.primitives import FEATURE_TERMINALS, build_primitive_set

        pset = build_primitive_set()
        # DEAP PrimitiveSet stores terminals in pset.arguments
        assert len(pset.arguments) == len(FEATURE_TERMINALS)

    def test_protected_div_zero(self):
        from agentic_forex.ml.primitives import protected_div

        result = protected_div(5.0, 0.0)
        assert result == 1.0

    def test_protected_div_normal(self):
        from agentic_forex.ml.primitives import protected_div

        assert abs(protected_div(6.0, 2.0) - 3.0) < 1e-9

    def test_gt_operator(self):
        from agentic_forex.ml.primitives import gt

        assert gt(2.0, 1.0) == 1.0
        assert gt(1.0, 2.0) == 0.0

    def test_lt_operator(self):
        from agentic_forex.ml.primitives import lt

        assert lt(1.0, 2.0) == 1.0
        assert lt(2.0, 1.0) == 0.0

    def test_and_operator(self):
        from agentic_forex.ml.primitives import and_

        assert and_(1.0, 1.0) == 1.0
        assert and_(1.0, 0.0) == 0.0
        assert and_(0.0, 0.0) == 0.0

    def test_or_operator(self):
        from agentic_forex.ml.primitives import or_

        assert or_(1.0, 0.0) == 1.0
        assert or_(0.0, 0.0) == 0.0

    def test_not_operator(self):
        from agentic_forex.ml.primitives import not_

        assert not_(1.0) == 0.0
        assert not_(0.0) == 1.0

    def test_protected_sqrt_negative(self):
        from agentic_forex.ml.primitives import protected_sqrt

        result = protected_sqrt(-4.0)
        assert result == 2.0

    def test_protected_log_nonpositive(self):
        from agentic_forex.ml.primitives import protected_log

        assert protected_log(0.0) == 0.0
        assert protected_log(-1.0) == 0.0

    def test_constant_range(self):
        from agentic_forex.ml.primitives import CONSTANT_RANGE

        lo, hi = CONSTANT_RANGE
        assert lo < hi


# ---------------------------------------------------------------------------
# P1.5.3-4 — GP discovery engine and parsimony
# ---------------------------------------------------------------------------


class TestGPDiscovery:
    def test_discovery_returns_result(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        # Minimal run: 10 individuals, 3 generations
        result = run_gp_discovery(X, y, population_size=10, generations=3, random_seed=0)
        assert result is not None
        assert result.best_rule is not None

    def test_best_rule_has_string(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        result = run_gp_discovery(X, y, population_size=10, generations=3, random_seed=1)
        assert isinstance(result.best_rule.rule_str, str)

    def test_tree_depth_capped(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        max_depth = 4
        result = run_gp_discovery(
            X,
            y,
            population_size=10,
            generations=3,
            max_tree_depth=max_depth,
            random_seed=2,
        )
        # All top rules must respect the cap
        for rule in result.top_rules:
            assert rule.tree_depth <= max_depth, (
                f"Rule depth {rule.tree_depth} exceeds cap {max_depth}: {rule.rule_str}"
            )

    def test_population_size_recorded(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        result = run_gp_discovery(X, y, population_size=8, generations=2, random_seed=3)
        assert result.population_size == 8

    def test_generations_recorded(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        result = run_gp_discovery(X, y, population_size=8, generations=2, random_seed=4)
        assert result.generations_run == 2

    def test_parsimony_coeff_recorded(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        result = run_gp_discovery(
            X,
            y,
            population_size=8,
            generations=2,
            parsimony_coefficient=0.05,
            random_seed=5,
        )
        assert result.parsimony_coefficient == 0.05

    def test_to_dict_keys(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        result = run_gp_discovery(X, y, population_size=8, generations=2, random_seed=6)
        d = result.to_dict()
        for key in [
            "best_rule_str",
            "best_oos_profit_factor",
            "best_fitness",
            "best_tree_depth",
            "population_size",
            "generations_run",
            "parsimony_coefficient",
            "max_tree_depth",
            "converged",
            "top_rules",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_top_rules_list(self):
        pytest.importorskip("deap")
        from agentic_forex.ml.gp_rules import run_gp_discovery

        X, y = _make_feature_matrix(200)
        result = run_gp_discovery(X, y, population_size=10, generations=3, n_top_rules=3, random_seed=7)
        assert len(result.top_rules) <= 3

    def test_evaluate_rule_on_features_zero_signals(self):
        from agentic_forex.ml.gp_rules import _evaluate_rule_on_features

        X = np.zeros((50, 5))
        y = np.ones(50, dtype=int)

        # A rule that always returns False
        def always_false(*_):
            return 0.0

        pf, wr, n = _evaluate_rule_on_features(always_false, X, y)
        assert n == 0
        assert pf == 0.0
        assert wr == 0.0

    def test_evaluate_rule_on_features_all_win(self):
        from agentic_forex.ml.gp_rules import _evaluate_rule_on_features

        X = np.zeros((50, 5))
        y = np.ones(50, dtype=int)

        # A rule that always returns True
        def always_true(*_):
            return 1.0

        pf, wr, n = _evaluate_rule_on_features(always_true, X, y, stop_loss_pips=10.0, take_profit_pips=15.0)
        assert n == 50
        assert wr == 1.0
        assert pf > 0


# ---------------------------------------------------------------------------
# P1.5.5 — GP step type in governance
# ---------------------------------------------------------------------------


class TestGPStepType:
    def test_discover_gp_rules_in_next_step_type(self):
        """discover_gp_rules must be in NextStepType Literal."""
        import typing

        from agentic_forex.governance.models import NextStepType

        args = typing.get_args(NextStepType)
        assert "discover_gp_rules" in args

    def test_discover_gp_rules_in_supported_step_types(self):
        """discover_gp_rules must be in SUPPORTED_STEP_TYPES set."""
        from agentic_forex.campaigns.next_step import SUPPORTED_STEP_TYPES

        assert "discover_gp_rules" in SUPPORTED_STEP_TYPES

    def test_gp_rules_settings_defaults(self):
        """GPRulesSettings must have sensible defaults."""
        from agentic_forex.config.models import GPRulesSettings

        cfg = GPRulesSettings()
        assert 50 <= cfg.population_size <= 500
        assert 20 <= cfg.generations <= 300
        assert 4 <= cfg.max_tree_depth <= 12
        assert 0.0 < cfg.parsimony_coefficient < 1.0
        assert 0.0 < cfg.crossover_probability <= 1.0
        assert 0.0 < cfg.mutation_probability <= 1.0
