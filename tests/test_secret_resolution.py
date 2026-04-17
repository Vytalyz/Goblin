from __future__ import annotations

from agentic_forex.cli.app import _setup_oanda_credential
from agentic_forex.config import load_settings
from agentic_forex.utils import secrets


def test_resolve_secret_prefers_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")
    seen_targets: list[str] = []

    def fake_reader(target: str) -> str | None:
        seen_targets.append(target)
        return "credential-secret"

    monkeypatch.setattr(secrets, "read_windows_credential", fake_reader)

    resolved = secrets.resolve_secret(
        env_var="OPENAI_API_KEY",
        credential_targets=["openai-api-key"],
    )

    assert resolved == "env-secret"
    assert seen_targets == []


def test_settings_fall_back_to_credential_manager(monkeypatch, project_root):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OANDA_API_TOKEN", raising=False)
    seen_targets: list[str] = []

    def fake_reader(target: str) -> str | None:
        seen_targets.append(target)
        if target == "openai-api-key":
            return "openai-from-credman"
        if target == "goblin/oanda/practice":
            return "oanda-from-credman"
        return None

    monkeypatch.setattr(secrets, "read_windows_credential", fake_reader)

    settings = load_settings(project_root=project_root)

    assert settings.llm.api_key() == "openai-from-credman"
    assert settings.oanda.api_token() == "oanda-from-credman"
    assert seen_targets == ["openai-api-key", "goblin/oanda/practice"]


def test_setup_oanda_credential_uses_hidden_prompt_and_preferred_target(project_root):
    settings = load_settings(project_root=project_root)
    prompts: list[str] = []
    writes: list[tuple[str, str, str, str | None]] = []
    values = iter(["new-token", "new-token"])

    def fake_prompt(prompt: str) -> str:
        prompts.append(prompt)
        return next(values)

    def fake_writer(target: str, secret: str, *, username: str = "api-token", comment: str | None = None) -> None:
        writes.append((target, secret, username, comment))

    result = _setup_oanda_credential(
        settings,
        prompt_secret=fake_prompt,
        writer=fake_writer,
    )

    assert prompts == [
        "Enter OANDA practice API token: ",
        "Confirm OANDA practice API token: ",
    ]
    assert writes == [
        (
            "goblin/oanda/practice",
            "new-token",
            "api-token",
            "Agentic Forex OANDA practice token",
        )
    ]
    assert result["stored"] is True
    assert result["target"] == "goblin/oanda/practice"
