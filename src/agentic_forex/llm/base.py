from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class LLMError(RuntimeError):
    pass


class BaseLLMClient(ABC):
    @abstractmethod
    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[BaseModel],
        payload: dict[str, Any] | None = None,
    ) -> BaseModel:
        raise NotImplementedError
