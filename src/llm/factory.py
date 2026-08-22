"""Build a provider client from a config block.

The generator and the judge each had their own copy of this switch, identical apart from the order
of the two branches and the noun in the error message. Order never mattered, since the conditions
are mutually exclusive, so the copies were the same function written twice.

Temperature is read from config and passed explicitly rather than left to the SDK default. The
ablation only means anything if the generator is provably identical across all six conditions, and
the recorded temperature is part of that claim, so it must not come from whatever a provider happens
to default to this month.
"""

from __future__ import annotations

from src.llm.base import LLMClient


def make_client(cfg: dict, *, role: str) -> LLMClient:
    """A client for the `llm.generator` or `llm.judge` config block.

    `role` names the caller in the error message only. It is worth carrying because the realistic
    failure is a config edit that points one of the two at an unsupported provider, and "unsupported
    judge provider" says which block to fix where "unsupported provider" does not.
    """
    provider = cfg["provider"].lower()
    model = cfg["model"]
    temperature = float(cfg["temperature"])
    if provider == "openai":
        from src.llm.openai_client import OpenAIClient   # lazy: keeps the SDK optional at import
        return OpenAIClient(model=model, temperature=temperature)
    if provider == "anthropic":
        from src.llm.anthropic_client import AnthropicClient   # lazy
        return AnthropicClient(model=model, temperature=temperature)
    raise ValueError(f"unsupported {role} provider: {provider!r}")
