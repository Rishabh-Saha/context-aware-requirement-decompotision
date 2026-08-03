"""Provider-agnostic LLM interface with retry. Generation and judging can therefore run on
different model families behind the same call, which the proposal relies on to keep the judge
independent of the generator."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    raw: object = None


class LLMClient(ABC):
    def __init__(self, model: str, temperature: float = 0.0, max_retries: int = 3, retry_base_delay: float = 2.0):
        self.model = model
        self.temperature = temperature   # fixed across all conditions; recorded with results
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

    @abstractmethod
    def _complete_once(self, prompt: str, system: str | None, **kwargs) -> LLMResponse: ...

    def complete(self, prompt: str, system: str | None = None, **kwargs) -> LLMResponse:
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return self._complete_once(prompt, system, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_base_delay * (2 ** attempt))
        raise RuntimeError(f"{self.model} failed after {self.max_retries} attempts") from last
