"""Layer 3 pairwise LLM judge (proposal Section 7.4). Comparison-pair generation and reconciliation
live in comparisons.py; this renders one ordered comparison, issues the judge call, and parses which
option won on the five criteria.

Two properties matter more than anything else here and are enforced rather than assumed. The judge
never learns which condition produced which side: the prompt carries only OUTPUT A and OUTPUT B, and
nothing in this module writes a condition name into it. And the parse is strict about the five
criteria: a response missing a criterion, or naming anything other than A or B, raises rather than
being coerced, because a silently defaulted winner would be indistinguishable from a real judgement
once it reaches the reconciliation step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.paths import DEFAULT_PROMPT

CRITERIA = ("actionability", "completeness", "project_specificity", "granularity", "clarity")

DEFAULT_PROMPT_PATH = Path(DEFAULT_PROMPT)

# The only two things a verdict may name. Kept explicit so a judge that answers "tie", "both" or a
# condition name fails loudly instead of quietly becoming a win for whichever side sorts first.
OPTIONS = ("A", "B")


@dataclass
class JudgeVerdict:
    winner: str        # "A" or "B"
    per_criterion: dict[str, str]   # criterion -> "A"/"B"
    rationale: str = ""


def load_template(path: str | Path = DEFAULT_PROMPT_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def render_judge_prompt(requirement: str, a_output: str, b_output: str, template: str) -> str:
    """Fill the judge template. Split out from the call so the rendered prompt can be asserted on in
    tests and archived without spending a judge call.

    str.format is safe despite the outputs containing braces, since format only scans the template
    for fields and never re-scans substituted values. The template escapes the braces of its own
    JSON example as {{ }} for the same reason.
    """
    return template.format(requirement=requirement, output_a=a_output, output_b=b_output)


def parse_judge_response(raw_text: str) -> JudgeVerdict:
    """Parse the judge's JSON verdict, tolerating ```json fences the way generation output is.

    Every criterion must be present and every choice must be A or B. Raising on anything else is
    deliberate: an unparseable verdict is recorded as a failure and the comparison is left unjudged,
    which is honest, whereas a filled-in default would enter the reconciliation and the win counts
    as though the judge had actually chosen.
    """
    cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge response was not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"judge response was {type(payload).__name__}, expected a JSON object")

    per_criterion: dict[str, str] = {}
    for criterion in CRITERIA:
        if criterion not in payload:
            raise ValueError(f"judge response is missing criterion {criterion!r}")
        choice = str(payload[criterion]).strip().upper()
        if choice not in OPTIONS:
            raise ValueError(f"criterion {criterion!r} chose {payload[criterion]!r}, expected A or B")
        per_criterion[criterion] = choice

    if "winner" not in payload:
        raise ValueError("judge response is missing 'winner'")
    winner = str(payload["winner"]).strip().upper()
    if winner not in OPTIONS:
        raise ValueError(f"winner was {payload['winner']!r}, expected A or B")

    return JudgeVerdict(
        winner=winner,
        per_criterion=per_criterion,
        rationale=str(payload.get("rationale", "")),
    )


def judge_pair(a_output: str, b_output: str, requirement: str, llm, template: str | None = None) -> JudgeVerdict:
    """One ordered pairwise judgement. `template` is passed in by the runner, which loads the prompt
    once for the whole pass; when omitted it is read from the default path.

    The judge model must be a different family from the generator to avoid self-enhancement bias.
    That is a property of the client handed in here, and the runner asserts it against the
    generation run's manifest before any call is made.
    """
    tmpl = template if template is not None else load_template()
    prompt = render_judge_prompt(requirement, a_output, b_output, tmpl)
    response = llm.complete(prompt)
    return parse_judge_response(response.text)
