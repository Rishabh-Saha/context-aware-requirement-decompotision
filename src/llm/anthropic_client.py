"""Anthropic-backed client, available as an alternative generator/judge family. Reads
ANTHROPIC_API_KEY from the environment."""

from __future__ import annotations

import os

from .base import LLMClient, LLMResponse


class AnthropicClient(LLMClient):
    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 4096, **kwargs):
        super().__init__(model=model, **kwargs)
        self.max_tokens = max_tokens
        self._client = None

    def _ensure(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        return self._client

    def _complete_once(self, prompt: str, system: str | None, **kwargs) -> LLMResponse:
        client = self._ensure()
        msg = client.messages.create(
            model=self.model,
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            temperature=self.temperature,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return LLMResponse(text=text, model=self.model, raw=msg)
