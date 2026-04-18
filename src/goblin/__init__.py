"""Goblin compatibility-first runtime namespace.

This package is the Goblin-primary namespace and forwards to the existing
agentic_forex runtime kernel during migration.
"""

from __future__ import annotations

import sys
from importlib import import_module

__all__ = ["__version__"]
__version__ = "0.1.0"


_ALIAS_PACKAGES = [
    "approval",
    "backtesting",
    "campaigns",
    "cli",
    "config",
    "corpus",
    "evals",
    "experiments",
    "features",
    "forward",
    "goblin",
    "governance",
    "industry",
    "knowledge",
    "labels",
    "llm",
    "market_data",
    "ml",
    "mt5",
    "nodes",
    "operator",
    "policy",
    "runtime",
    "utils",
    "workflows",
]

for package_name in _ALIAS_PACKAGES:
    legacy_name = f"agentic_forex.{package_name}"
    goblin_name = f"goblin.{package_name}"
    if goblin_name not in sys.modules:
        sys.modules[goblin_name] = import_module(legacy_name)
