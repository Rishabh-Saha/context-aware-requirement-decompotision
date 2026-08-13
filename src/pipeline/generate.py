"""Run one ablation condition on one requirement and parse the result into the fixed schema
(proposal Sections 7.2-7.3).

Retrieval is per context type (docs/DECISION_retrieval_budget.md, Option B): every active type gets
its own budget and its own labelled prompt block, and a leave-one-out condition drops the type from
`active` so its block is never built. The only thing that varies across the six conditions here is
which types are active, which is what keeps the ablation attributable to context composition."""

from __future__ import annotations

import json

from src.conditions import Condition, active_contexts
from src.pipeline.prompt_assembly import build_prompt
from src.retrieval.hybrid import PER_TYPE, retrieve_by_type, self_exclusion_ids
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


def _field(requirement, name: str):
    """Read a field off either a SampledRequirement or the frozen-JSON dict of the same shape."""
    if isinstance(requirement, dict):
        return requirement[name]
    return getattr(requirement, name)


def system_prompt() -> str:
    """The instruction plus the output contract. The schema comes from the Pydantic model, so what
    the model is told to emit cannot drift from what parse_decomposition validates."""
    return f"{SYSTEM_PROMPT}\n\nJSON schema:\n{json.dumps(output_json_schema(), indent=2)}"


def build_condition_prompt(requirement, condition: Condition, index, loader, per_type: int = PER_TYPE) -> str:
    """The assembled user prompt for one (requirement, condition) pair. Split out from the LLM call
    so a prompt can be inspected, logged with the run, or diffed across conditions without spending
    a generation."""
    issue_key = _field(requirement, "issue_key")
    title = _field(requirement, "title")
    description = _field(requirement, "description")

    active = active_contexts(condition)
    # Vanilla has no active types, so it retrieves nothing and never needs the exclusion lookup.
    excluded = self_exclusion_ids(loader, issue_key) if active else {issue_key}
    retrieved = retrieve_by_type(
        f"{title}\n{description}",
        active,
        index,
        per_type=per_type,
        exclude_issue_id=issue_key,
        exclude_issue_ids=excluded - {issue_key},
    )
    return build_prompt(title, description, retrieved)


def run_condition(
    requirement, condition: Condition, index, loader, llm, per_type: int = PER_TYPE
) -> Decomposition:
    """Retrieve per active context type, assemble the prompt, generate, and validate the result."""
    prompt = build_condition_prompt(requirement, condition, index, loader, per_type=per_type)
    response = llm.complete(prompt, system=system_prompt())
    return parse_decomposition(response.text)
