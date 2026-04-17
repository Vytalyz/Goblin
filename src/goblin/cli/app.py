"""Goblin primary CLI entrypoint.

This currently forwards to the legacy runtime CLI implementation to preserve
behavior while the namespace migration is in progress.
"""

from __future__ import annotations

from agentic_forex.cli.app import main


__all__ = ["main"]
