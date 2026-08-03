"""Layer 3 pairwise LLM judge (proposal Section 7.4). Comparison-pair generation and reconciliation
live in comparisons.py; this issues the judge call for one ordered comparison and parses which
option won on the five criteria. Judge call is scaffolded."""

from __future__ import annotations

from dataclasses import dataclass

CRITERIA = ("actionability", "completeness", "project_specificity", "granularity", "clarity")


@dataclass
class JudgeVerdict:
    winner: str        # "A" or "B"
    per_criterion: dict[str, str]   # criterion -> "A"/"B"
    rationale: str = ""


def judge_pair(a_output: str, b_output: str, requirement: str, llm) -> JudgeVerdict:
    """TODO(rishabh): render prompts/judge_pairwise.txt with the two outputs and requirement, call
    the judge llm, parse the per-criterion winners and an overall winner. Keep the judge model in a
    different family from the generator to avoid self-enhancement bias."""
    raise NotImplementedError("Render judge_pairwise.txt, call llm, parse per-criterion winners.")
