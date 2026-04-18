#!/usr/bin/env bash
# Goblin Guardian: One-Command Setup
# Run this from the repository root to install all dev tools and activate Guardian hooks.
#
# Usage:
#   bash scripts/setup-guardian.sh

set -euo pipefail

echo ""
echo "=== Goblin Guardian Setup ==="

# Install the project with dev dependencies
echo ""
echo "[1/3] Installing project with dev dependencies..."
pip install -e ".[dev]"

# Install pre-commit hooks (commit + push)
echo ""
echo "[2/3] Installing pre-commit hooks..."
pre-commit install
pre-commit install --hook-type pre-push

# Verify
echo ""
echo "[3/3] Verifying setup..."
echo "  ruff:       $(ruff --version)"
echo "  pytest:     $(python -m pytest --version 2>&1 | head -1)"
echo "  pre-commit: $(pre-commit --version)"

echo ""
echo "=== Guardian is watching. Your coins are safe! ==="
