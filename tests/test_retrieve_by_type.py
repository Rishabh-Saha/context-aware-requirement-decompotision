"""Tests for per-type retrieval (docs/DECISION_retrieval_budget.md, Option B) and the generate.py
wiring that consumes it.

The index and the loader are fakes rather than a real ChromaDB collection: hybrid_retrieve is
already covered against real chroma in test_hybrid.py, so what needs pinning down here is the layer
above it, namely that each active type gets its own budget, that a leave-one-out drops exactly one
type, and that self-exclusion still holds once results are grouped by type. Keeping those checks on
a fake index makes the per-type behaviour deterministic and keeps the suite offline.
"""

import json

import pytest

from src.conditions import ALL_CONTEXT_TYPES, Condition, ContextType, LEAVE_ONE_OUT, active_contexts
from src.pipeline.generate import build_condition_prompt, run_condition
from src.retrieval.hybrid import PER_TYPE, retrieve_by_type

REQUIREMENT = {
    "issue_key": "PIG-1",
    "title": "csv storage loader",
    "description": "add a csv storage loader to pig",
}


class FakeIndex:
    """Enough of ContextIndex for retrieval: a type-filtered get() and a dense query that ranks by
    token overlap with the query. Same contract as chroma's, including the issue_id exclusion the
    dense channel applies through its metadata filter."""

    def __init__(self, records: list[tuple[str, str, ContextType, str | None]]):
        # (id, text, context_type, issue_id)
        self.records = records

    def _active(self, active):
        wanted = {c.value for c in active}
        return [r for r in self.records if r[2].value in wanted]

    def chunks_for_types(self, active):
        if not active:
            return [], [], []
        rows = self._active(active)
        ids = [r[0] for r in rows]
        docs = [r[1] for r in rows]
        metas = [{"context_type": r[2].value, "issue_id": r[3]} for r in rows]
        return ids, docs, metas

    def dense_query(self, query_embedding, active, top_k, exclude_issue_id=None):
        if not active:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]]}
        rows = [r for r in self._active(active) if r[3] != exclude_issue_id or exclude_issue_id is None]
        # query_embedding is the fake embedding below: the query's own token set.
        q = set(query_embedding)
        rows.sort(key=lambda r: -len(q & set(r[1].split())))
        rows = rows[:top_k]
        return {
            "ids": [[r[0] for r in rows]],
            "documents": [[r[1] for r in rows]],
            "metadatas": [[{"context_type": r[2].value, "issue_id": r[3]} for r in rows]],
        }


class FakeLoader:
    """Only the one method self_exclusion_ids calls. PIG-1a is PIG-1's containment sub-task, that
    is, the human decomposition the model must never be shown."""

    LINKS = {"PIG-1": ["PIG-1a"]}

    def linked_issue_ids(self, issue_id, containment_only=False):
        return self.LINKS.get(issue_id, [])


class FakeLLM:
    """Records the prompt it was handed and replays a fixed valid decomposition."""

    RESPONSE = {
        "epic_summary": "Add csv storage support",
        "user_stories": [
            {
                "id": "US-1",
                "story": "As a pig user, I want a csv loader, so that scripts can read csv.",
                "acceptance_criteria": ["loads a csv file"],
                "complexity": "M",
                "dependencies": [],
                "source_files": ["CSVStorage.java"],
            }
        ],
    }

    def __init__(self):
        self.prompt = None
        self.system = None

    def complete(self, prompt, system=None, **kwargs):
        self.prompt = prompt
        self.system = system
        return type("R", (), {"text": "```json\n" + json.dumps(self.RESPONSE) + "\n```"})()


def _fake_embed(texts):
    # The "embedding" is just the query's token set, which FakeIndex.dense_query ranks against.
    return [set(t.split()) for t in texts]


@pytest.fixture
def index() -> FakeIndex:
    # At least three eligible chunks per type so a budget of two or three actually has to cut
    # something. The past_tickets set carries two extra entries, the requirement itself and its
    # sub-task, both strong lexical matches, which self-exclusion has to remove.
    return FakeIndex([
        ("pt::PIG-1::0", "csv storage loader for pig", ContextType.PAST_TICKETS, "PIG-1"),
        ("pt::PIG-1a::0", "csv storage loader subtask writer", ContextType.PAST_TICKETS, "PIG-1a"),
        ("pt::PIG-2::0", "csv parser storage work", ContextType.PAST_TICKETS, "PIG-2"),
        ("pt::PIG-3::0", "csv loader rework", ContextType.PAST_TICKETS, "PIG-3"),
        ("pt::PIG-4::0", "csv storage cleanup", ContextType.PAST_TICKETS, "PIG-4"),
        ("dd::basic::0", "csv load and store design", ContextType.DESIGN_DOCS, None),
        ("dd::basic::1", "storage design notes csv", ContextType.DESIGN_DOCS, None),
        ("dd::basic::2", "loader design overview csv", ContextType.DESIGN_DOCS, None),
        ("cc::style::0", "csv naming conventions storage", ContextType.CODING_CONVENTIONS, None),
        ("cc::style::1", "loader conventions csv", ContextType.CODING_CONVENTIONS, None),
        ("cc::style::2", "storage conventions csv", ContextType.CODING_CONVENTIONS, None),
        ("cs::CSVStorage::0", "csv storage class summary", ContextType.CODEBASE_SUMMARIES, None),
        ("cs::Loader::0", "loader class summary csv", ContextType.CODEBASE_SUMMARIES, None),
        ("cs::Parser::0", "parser class summary csv", ContextType.CODEBASE_SUMMARIES, None),
    ])


def _retrieve(index, active, per_type=PER_TYPE):
    return retrieve_by_type(
        "csv storage loader",
        active,
        index,
        per_type=per_type,
        embed_fn=_fake_embed,
        exclude_issue_id="PIG-1",
        exclude_issue_ids={"PIG-1a"},
    )


def test_full_rag_covers_every_type_within_budget(index):
    got = _retrieve(index, active_contexts(Condition.FULL_RAG))
    assert set(got) == set(ALL_CONTEXT_TYPES)
    assert all(0 < len(chunks) <= PER_TYPE for chunks in got.values())


@pytest.mark.parametrize("condition", LEAVE_ONE_OUT)
def test_leave_one_out_drops_exactly_its_type(index, condition):
    active = active_contexts(condition)
    dropped = set(ALL_CONTEXT_TYPES) - set(active)
    got = _retrieve(index, active)
    assert set(got) == set(active)
    assert len(dropped) == 1 and not (set(got) & dropped)


def test_excluded_issues_never_appear(index):
    """PIG-1 and its sub-task PIG-1a are the two best lexical matches for this query, so a per-type
    budget that skipped self-exclusion would surface both in the past_tickets block."""
    got = _retrieve(index, active_contexts(Condition.FULL_RAG))
    leaked = {"csv storage loader for pig", "csv storage loader subtask writer"}
    assert not (set(got[ContextType.PAST_TICKETS]) & leaked)


def test_budget_is_per_type_not_global(index):
    """The point of Option B: past_tickets cannot spend another type's slots, so the total is
    per_type times the number of active types rather than one shared pool."""
    got = _retrieve(index, active_contexts(Condition.FULL_RAG), per_type=3)
    assert sum(len(v) for v in got.values()) == 3 * len(ALL_CONTEXT_TYPES)


def test_vanilla_retrieves_nothing(index):
    assert _retrieve(index, active_contexts(Condition.VANILLA)) == {}


def test_prompt_has_one_block_per_active_type(index):
    prompt = build_condition_prompt(REQUIREMENT, Condition.NO_DESIGN_DOCS, index, FakeLoader())
    assert "## PAST TICKETS" in prompt
    assert "## DESIGN DOCUMENTS" not in prompt
    assert "## CODING CONVENTIONS" in prompt
    assert "## CODEBASE SUMMARIES" in prompt
    assert prompt.index("## REQUIREMENT") > prompt.index("## PAST TICKETS")


def test_vanilla_prompt_carries_no_context(index):
    prompt = build_condition_prompt(REQUIREMENT, Condition.VANILLA, index, FakeLoader())
    assert prompt.startswith("## REQUIREMENT")
    assert REQUIREMENT["title"] in prompt


def test_run_condition_parses_the_generation(index):
    llm = FakeLLM()
    result = run_condition(REQUIREMENT, Condition.FULL_RAG, index, FakeLoader(), llm)
    assert result.epic_summary == "Add csv storage support"
    assert result.story_ids() == {"US-1"}
    assert "## PAST TICKETS" in llm.prompt
    assert "user_stories" in llm.system      # the output contract travels with the system prompt
