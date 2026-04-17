from __future__ import annotations

import json

from pydantic import BaseModel

from agentic_forex.config import Settings
from agentic_forex.llm.base import BaseLLMClient, LLMError


class OpenAIClient(BaseLLMClient):
    """Optional legacy live LLM adapter.

    The Codex-native operator is the primary planner for this repo. This client
    remains available only for explicit legacy live-discovery or review flows.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[BaseModel],
        payload: dict | None = None,
    ) -> BaseModel:
        api_key = self.settings.llm.api_key()
        if not api_key:
            raise LLMError(
                "OpenAI API key is unavailable. Set "
                f"{self.settings.llm.api_key_env} or store a Windows Credential Manager secret under "
                f"{', '.join(self.settings.llm.credential_targets)}."
            )
        try:
            from openai import OpenAI, OpenAIError, RateLimitError
        except ImportError as exc:  # pragma: no cover
            raise LLMError("openai package is not installed.") from exc

        client = OpenAI(api_key=api_key)
        try:
            response = client.chat.completions.create(
                model=self.settings.llm.openai_model,
                temperature=self.settings.llm.temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task_name": task_name,
                                "payload": payload or {},
                                "schema_name": schema_model.__name__,
                                "instruction": "Return only JSON matching the requested schema.",
                            },
                            indent=2,
                            default=str,
                        ),
                    },
                ],
            )
        except RateLimitError as exc:
            message = str(exc)
            if "insufficient_quota" in message:
                raise LLMError(
                    "OpenAI API key resolved successfully, but the account/project has no available API quota. "
                    "Update OpenAI billing/quota or supply a different API key before running live discovery."
                ) from exc
            raise LLMError(f"OpenAI rate limit error: {message}") from exc
        except OpenAIError as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc
        content = response.choices[0].message.content or "{}"
        return schema_model.model_validate_json(content)
