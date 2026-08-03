"""Layer 1: structural metrics (proposal Section 7.4).

Diagnostic descriptors of a decomposition's shape, computed automatically and unaffected by
LLM-judge bias. These are reported as descriptors of output shape, not as quality scores: more
stories or more real file references does not by itself mean a better decomposition.

Metrics per the proposal:
    number of user stories
    well-formedness against the user-story template
    acceptance criteria per story
    file-reference specificity (proportion of stories citing specific files vs generic references)
    inter-story dependency rate
"""

from __future__ import annotations

import re
from statistics import mean

from src.schema import Decomposition, UserStory

# A file reference is "specific" if it looks like an actual path or filename (has a slash or a
# dotted extension) rather than a generic gesture like "the parser" or "relevant modules".
_SPECIFIC_FILE = re.compile(r"(/|\.[A-Za-z0-9]{1,6}$)")


def _story_cites_specific_file(story: UserStory) -> bool:
    return any(_SPECIFIC_FILE.search(ref.strip()) for ref in story.source_files if ref.strip())


def structural_metrics(decomp: Decomposition) -> dict:
    stories = decomp.user_stories
    n = len(stories)
    if n == 0:
        return {
            "num_user_stories": 0,
            "well_formedness_rate": 0.0,
            "avg_acceptance_criteria": 0.0,
            "file_reference_specificity": 0.0,
            "inter_story_dependency_rate": 0.0,
            "dangling_dependency_count": 0,
        }
    return {
        "num_user_stories": n,
        "well_formedness_rate": round(sum(s.is_well_formed for s in stories) / n, 4),
        "avg_acceptance_criteria": round(mean(len(s.acceptance_criteria) for s in stories), 4),
        "file_reference_specificity": round(
            sum(_story_cites_specific_file(s) for s in stories) / n, 4
        ),
        "inter_story_dependency_rate": round(
            sum(1 for s in stories if s.dependencies) / n, 4
        ),
        "dangling_dependency_count": len(decomp.dangling_dependencies()),
    }
