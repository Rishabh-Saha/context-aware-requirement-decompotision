"""Shared record shape so every layer logs uniformly to W&B / DVC."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalRecord:
    layer: str
    metrics: dict[str, float]
    details: dict[str, Any] = field(default_factory=dict)
