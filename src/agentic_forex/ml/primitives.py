"""Feature primitive set for Genetic Programming rule discovery (ML-P1.5).

Defines the terminals (feature columns) and functional operators that DEAP
uses to build boolean expression trees.  Each evolved tree represents a
candidate entry rule: True → enter trade, False → skip.

Operator naming follows DEAP conventions.  All arithmetic operators are
protected against division-by-zero and NaN propagation.
"""

from __future__ import annotations

import math
import operator as _op
from typing import Callable

import numpy as np

# ---------------------------------------------------------------------------
# Feature column names available as GP terminals
# These must match the columns produced by features/service.py
# ---------------------------------------------------------------------------
FEATURE_TERMINALS: list[str] = [
    "ret_1",
    "ret_5",
    "zscore_10",
    "momentum_12",
    "volatility_20",
    "intrabar_range_pips",
    "range_position_10",
    "spread_to_range_10",
    "spread_pips",
    "hour",
    "regime_label",
]

# ---------------------------------------------------------------------------
# Numeric constants used as ephemeral random constants in GP trees
# ---------------------------------------------------------------------------
CONSTANT_RANGE: tuple[float, float] = (-3.0, 3.0)


# ---------------------------------------------------------------------------
# Protected arithmetic operators
# ---------------------------------------------------------------------------

def protected_div(a: float, b: float) -> float:
    """Division protected against zero denominator."""
    if abs(b) < 1e-9:
        return 1.0
    return a / b


def protected_sqrt(a: float) -> float:
    """Square root protected against negative inputs."""
    return math.sqrt(abs(a))


def protected_log(a: float) -> float:
    """Natural log protected against non-positive inputs."""
    if a <= 0:
        return 0.0
    return math.log(a)


def add(a: float, b: float) -> float:
    return _op.add(a, b)


def sub(a: float, b: float) -> float:
    return _op.sub(a, b)


def mul(a: float, b: float) -> float:
    return _op.mul(a, b)


def neg(a: float) -> float:
    return _op.neg(a)


# ---------------------------------------------------------------------------
# Comparison operators — return float 1.0/0.0 so trees stay numeric
# ---------------------------------------------------------------------------

def gt(a: float, b: float) -> float:
    return 1.0 if a > b else 0.0


def lt(a: float, b: float) -> float:
    return 1.0 if a < b else 0.0


def ge(a: float, b: float) -> float:
    return 1.0 if a >= b else 0.0


def le(a: float, b: float) -> float:
    return 1.0 if a <= b else 0.0


# ---------------------------------------------------------------------------
# Logical operators on float (0.0 = False, non-zero = True)
# ---------------------------------------------------------------------------

def and_(a: float, b: float) -> float:
    return 1.0 if (a != 0.0 and b != 0.0) else 0.0


def or_(a: float, b: float) -> float:
    return 1.0 if (a != 0.0 or b != 0.0) else 0.0


def not_(a: float) -> float:
    return 0.0 if a != 0.0 else 1.0


# ---------------------------------------------------------------------------
# Public operator registry — used by gp_rules.py to build the primitive set
# ---------------------------------------------------------------------------

# (name, function, arity)
BINARY_OPS: list[tuple[str, Callable, int]] = [
    ("add", add, 2),
    ("sub", sub, 2),
    ("mul", mul, 2),
    ("div", protected_div, 2),
    ("gt", gt, 2),
    ("lt", lt, 2),
    ("ge", ge, 2),
    ("le", le, 2),
    ("and_", and_, 2),
    ("or_", or_, 2),
]

UNARY_OPS: list[tuple[str, Callable, int]] = [
    ("neg", neg, 1),
    ("not_", not_, 1),
    ("sqrt", protected_sqrt, 1),
    ("log", protected_log, 1),
]

ALL_OPS: list[tuple[str, Callable, int]] = BINARY_OPS + UNARY_OPS


def build_primitive_set(n_features: int | None = None) -> object:
    """Build and return a DEAP PrimitiveSet for GP rule discovery.

    Args:
        n_features: Number of feature terminals.  Defaults to
            ``len(FEATURE_TERMINALS)``.

    Returns:
        A ``deap.gp.PrimitiveSet`` instance ready for use in GP evolution.
    """
    from deap import gp  # lazy import — deap is optional until ML-P1.5

    n = n_features if n_features is not None else len(FEATURE_TERMINALS)
    pset = gp.PrimitiveSet("ENTRY_RULE", n)

    # Rename ARGn to meaningful feature names
    for i, col in enumerate(FEATURE_TERMINALS[:n]):
        pset.renameArguments(**{f"ARG{i}": col})

    # Register all operators
    for name, func, arity in ALL_OPS:
        pset.addPrimitive(func, arity, name=name)

    # Ephemeral constant: random float in CONSTANT_RANGE each time it appears
    import random

    def rand_const() -> float:
        lo, hi = CONSTANT_RANGE
        return round(random.uniform(lo, hi), 4)

    pset.addEphemeralConstant("const", rand_const)

    return pset
