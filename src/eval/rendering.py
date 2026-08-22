"""How a comparison side is shown to a rater, whether that rater is the LLM judge (Layer 3) or the
researcher (Layer 4).

This lives in one module on purpose. Layer 4 only means anything if the researcher and the judge
scored the same stimulus, so the calibration script must not carry its own copy of the renderers
that could drift from the judge's. Both scripts import from here, which makes "the human saw exactly
what the judge saw" a property of the code rather than a claim in a docstring.

Nothing here emits a condition name, the reference sentinel, or any provenance label. Blinding is
enforced at the point where text is produced, not patched up afterwards by the callers.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.eval.comparisons import REFERENCE

# Commit-message trailers carry no requirement content and are a plain giveaway that a side came
# from version control rather than from a model, so they are stripped before either rater sees them.
TRAILER_PREFIXES = ("git-svn-id:", "signed-off-by:", "reviewed-by:", "co-authored-by:",
                    "reviewed by:", "patch by:", "contributed by:")


def render_decomposition(decomp: dict) -> str:
    """A decomposition as plain prose.

    Deliberately not JSON. The reference side is human prose, so emitting the model side as JSON
    would let a rater separate the two on formatting alone in the SQ3 comparisons. A common
    plain-text renderer does not make the two sides indistinguishable, but it removes the most
    obvious tell, and nothing here names the condition that produced the text.
    """
    lines = [decomp.get("epic_summary", "").strip(), ""]
    for story in decomp.get("user_stories", []):
        lines.append(f"Story {story.get('id', '')}: {story.get('story', '').strip()}")
        for criterion in story.get("acceptance_criteria", []):
            lines.append(f"  - {criterion}")
        lines.append(f"  Complexity: {story.get('complexity', '')}")
        if story.get("dependencies"):
            lines.append(f"  Depends on: {', '.join(story['dependencies'])}")
        if story.get("source_files"):
            lines.append(f"  Files: {', '.join(story['source_files'])}")
        lines.append("")
    return "\n".join(lines).strip()


def scrub_artefact(text: str, issue_key: str) -> str:
    """Remove the provenance tells from a reference artefact without touching its substance.

    Two things go: commit trailers, and the issue key where it prefixes a commit subject line. Both
    identify the side as human-authored project history, which would let a rater answer the SQ3
    comparisons on provenance instead of on the five criteria. The requirement text itself, which is
    what the comparison is actually about, is left exactly as written.
    """
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.lower().startswith(p) for p in TRAILER_PREFIXES):
            continue
        if stripped.startswith(f"{issue_key} ") or stripped.startswith(f"{issue_key}:"):
            stripped = stripped[len(issue_key):].lstrip(": ").strip()
            line = stripped
        kept.append(line)
    # Trailer removal tends to leave a run of blank lines behind, which is itself a small tell.
    out: list[str] = []
    for line in kept:
        if not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line)
    return "\n".join(out).strip()


def render_reference(requirement: dict) -> str:
    """The human-authored SEOSS artefacts for a requirement, as the SQ3 comparison side.

    No label says these are the reference or that a human wrote them, since telling a rater which
    side is the ground truth would decide the comparison before it started.
    """
    issue_key = requirement["issue_key"]
    artefacts = [scrub_artefact(a, issue_key) for a in requirement.get("reference_artefacts", [])
                 if a and a.strip()]
    artefacts = [a for a in artefacts if a]
    if not artefacts:
        raise ValueError(f"{requirement['issue_key']} has no reference_artefacts to compare against")
    return "\n\n".join(artefacts)


def requirement_text(requirement: dict) -> str:
    """The requirement both sides are answering. Title and description only: issue metadata is kept
    out of rating prompts for the same reason it is kept out of the generation prompts."""
    return f"{requirement['title']}\n\n{requirement['description']}".strip()


def cell_stem(issue_key: str, condition: str) -> str:
    """The filename stem for one cell of the generation grid.

    run_experiment.py writes `<stem>.json` and `<stem>.prompt.txt`; load_decomposition below reads
    the first of those back, and the Layer 4 sheet reaches it through resolve_side. All of them come
    through here so the archive layout is stated in one place. A writer and a reader that agreed only
    by convention would diverge silently, and the symptom would be a FileNotFoundError for a file
    sitting in the directory under a slightly different name.
    """
    return f"{issue_key}__{condition}"


def load_decomposition(run_dir: str | Path, issue_key: str, condition: str) -> dict:
    """The archived decomposition for one cell of the generation grid.

    A missing file is an error rather than a skip. Silently dropping a side would leave a
    requirement contributing to some comparisons and not others, which is far harder to notice
    later than a recorded failure.
    """
    path = Path(run_dir) / f"{cell_stem(issue_key, condition)}.json"
    if not path.exists():
        raise FileNotFoundError(f"no archived decomposition at {path}")
    return json.loads(path.read_text())["decomposition"]


def resolve_side(name: str, requirement: dict, run_dir: str | Path) -> str:
    """Text for one side of a comparison, whether it is a condition or the reference sentinel."""
    if name == REFERENCE:
        return render_reference(requirement)
    return render_decomposition(load_decomposition(run_dir, requirement["issue_key"], name))
