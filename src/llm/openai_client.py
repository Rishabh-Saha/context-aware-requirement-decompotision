"""OpenAI-backed client (proposal names OpenAI for embeddings; the proprietary generation/judge
model is selected at experiment time). Reads OPENAI_API_KEY from the environment."""

from __future__ import annotations

import os

from .base import LLMClient, LLMResponse


class OpenAIClient(LLMClient):
    def __init__(self, model: str = "gpt-4o", **kwargs):
        super().__init__(model=model, **kwargs)
        self._client = None

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        return self._client

    def _complete_once(self, prompt: str, system: str | None, **kwargs) -> LLMResponse:
        client = self._ensure()
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        resp = client.chat.completions.create(
            model=self.model, messages=messages, temperature=self.temperature, **kwargs
        )
        return LLMResponse(text=resp.choices[0].message.content, model=self.model, raw=resp)


def embed_texts(texts: list[str], model: str = "text-embedding-3-small") -> list[list[float]]:
    """Batch embeddings with the model fixed in the proposal."""
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]
