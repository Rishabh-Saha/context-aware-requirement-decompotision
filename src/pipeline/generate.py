"""Run one ablation condition on one requirement and parse the result into the fixed schema
(proposal Sections 7.2-7.3). Assembly and parsing are ready; the retrieve+generate wiring is the
scaffold to complete once retrieval and the LLM client are live."""

from __future__ import annotations

import json

from src.conditions import Condition, active_contexts
from src.pipeline.prompt_assembly import build_prompt
from src.schema import Decomposition, output_json_schema

SYSTEM_PROMPT = (
    "You decompose a business requirement into developer-ready user stories. "
    "Return only JSON matching the provided schema: an epic summary and a list of user stories, "
    "each with acceptance criteria, a complexity estimate (S/M/L), dependencies on other story "
    "ids, and suggested source files. Ground file references in the provided context; do not "
    "invent paths."
)


def parse_decomposition(raw_text: str) -> Decomposition:
    """Parse and validate model output, tolerating ```json fences."""
    cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return Decomposition.model_validate(json.loads(cleaned))


def run_condition(requirement, condition: Condition, retriever, llm) -> Decomposition:
    """TODO(rishabh): for non-vanilla conditions, retrieve per active_contexts(condition) and pass
    the chunks into build_prompt; for vanilla, pass no retrieved context. Then call the llm with
    SYSTEM_PROMPT + output_json_schema() and parse_decomposition(response)."""
    _ = (active_contexts(condition), build_prompt, output_json_schema)  # referenced for the wiring
    raise NotImplementedError("Wire retrieve -> build_prompt -> llm.complete -> parse_decomposition.")
