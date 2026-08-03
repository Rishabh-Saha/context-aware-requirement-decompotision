"""The fixed JSON schema the LLM must emit for every decomposition (proposal Section 7.2).

Every downstream layer reads this shape, so it is the contract the whole pipeline agrees on:
an epic summary plus a list of user stories, each carrying acceptance criteria, a complexity
estimate, dependencies on other stories, and suggested source files. Keeping it as a Pydantic
model means malformed generations fail loudly at parse time rather than silently skewing the
structural metrics later.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator

# A user story is "well-formed" (Layer 1) when it follows the role/goal/benefit template that
# the INVEST and QUS frameworks assume. This pattern is intentionally lenient on wording but
# requires all three clauses to be present.
WELL_FORMED_PATTERN = re.compile(
    r"as an?\s+.+?,?\s+i\s+want\s+.+?,?\s+so\s+that\s+.+",
    re.IGNORECASE | re.DOTALL,
)


class Complexity(str, Enum):
    S = "S"
    M = "M"
    L = "L"


class UserStory(BaseModel):
    id: str = Field(..., description="Stable id, e.g. US-1, used by dependencies to reference it.")
    story: str = Field(..., description="Role/goal/benefit statement.")
    acceptance_criteria: list[str] = Field(default_factory=list)
    complexity: Complexity
    dependencies: list[str] = Field(
        default_factory=list, description="ids of stories that must land first."
    )
    source_files: list[str] = Field(
        default_factory=list, description="Suggested files this story would touch."
    )

    @property
    def is_well_formed(self) -> bool:
        return bool(WELL_FORMED_PATTERN.search(self.story or ""))

    @field_validator("id")
    @classmethod
    def _non_empty_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("user story id must be non-empty")
        return v.strip()


class Decomposition(BaseModel):
    epic_summary: str
    user_stories: list[UserStory]

    def story_ids(self) -> set[str]:
        return {s.id for s in self.user_stories}

    def dangling_dependencies(self) -> list[tuple[str, str]]:
        """Dependencies that point at a story id which does not exist in this decomposition."""
        ids = self.story_ids()
        return [
            (s.id, dep)
            for s in self.user_stories
            for dep in s.dependencies
            if dep not in ids
        ]


# The JSON Schema handed to the model in the prompt. Generated from the Pydantic model so the
# contract cannot drift between what is validated and what the model is told to produce.
def output_json_schema() -> dict:
    return Decomposition.model_json_schema()
