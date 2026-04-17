from __future__ import annotations

import importlib


def test_goblin_namespace_aliases_core_modules() -> None:
    goblin_config = importlib.import_module("goblin.config")
    legacy_config = importlib.import_module("agentic_forex.config")
    assert goblin_config is legacy_config

    goblin_campaigns = importlib.import_module("goblin.campaigns")
    legacy_campaigns = importlib.import_module("agentic_forex.campaigns")
    assert goblin_campaigns is legacy_campaigns


def test_goblin_cli_entrypoint_forwards() -> None:
    goblin_cli = importlib.import_module("goblin.cli.app")
    legacy_cli = importlib.import_module("agentic_forex.cli.app")
    assert goblin_cli.main.__name__ == "main"
    assert legacy_cli.main.__name__ == "main"
    assert goblin_cli.__file__ == legacy_cli.__file__


def test_submodule_import_through_goblin_namespace() -> None:
    goblin_models = importlib.import_module("goblin.config.models")
    legacy_models = importlib.import_module("agentic_forex.config.models")
    assert goblin_models.__file__ == legacy_models.__file__
    assert goblin_models.LLMSettings.model_fields.keys() == legacy_models.LLMSettings.model_fields.keys()
