"""Integration tests for ContextIndex against a real (temp-dir) ChromaDB PersistentClient - no
mocking of chromadb itself, since that's exactly the part worth verifying end to end. Embeddings
are a small deterministic fake (no OpenAI calls): each text maps to a fixed-length vector so
cosine similarity behaves predictably for the two probe queries used below.
"""

from pathlib import Path

import pytest

from src.conditions import ContextType
from src.retrieval.index import ContextIndex
from src.retrieval.sources import Chunk

pytest.importorskip("chromadb")


def _fake_embed(texts: list[str]) -> list[list[float]]:
    # Deterministic: vector is [1, 0] if "alpha" is in the text, else [0, 1]. Lets us assert which
    # chunks a query "about alpha" should retrieve without a real embedding model.
    return [[1.0, 0.0] if "alpha" in t else [0.0, 1.0] for t in texts]


@pytest.fixture
def index(tmp_path: Path) -> ContextIndex:
    return ContextIndex(collection_name="test_collection", persist_dir=str(tmp_path / "chroma"))


def test_add_chunks_splits_embeds_and_upserts(index):
    chunks = [
        Chunk(id="past_ticket::PIG-1", text="alpha issue text", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-1"}),
        Chunk(id="design_doc::basic", text="beta doc text", context_type=ContextType.DESIGN_DOCS,
              metadata={"source": "basic.xml"}),
    ]
    n = index.add_chunks(chunks, embed_fn=_fake_embed)
    assert n == 2  # each chunk's short text is one splitter piece

    got = index._ensure().get(ids=["past_ticket::PIG-1::0", "design_doc::basic::0"])
    assert set(got["ids"]) == {"past_ticket::PIG-1::0", "design_doc::basic::0"}


def test_add_chunks_is_idempotent_via_upsert(index):
    chunk = [Chunk(id="past_ticket::PIG-1", text="alpha issue text",
                    context_type=ContextType.PAST_TICKETS, metadata={"issue_id": "PIG-1"})]
    index.add_chunks(chunk, embed_fn=_fake_embed)
    index.add_chunks(chunk, embed_fn=_fake_embed)  # re-add: must not raise or duplicate
    got = index._ensure().get(where={"context_type": ContextType.PAST_TICKETS.value})
    assert got["ids"] == ["past_ticket::PIG-1::0"]


def test_dense_query_filters_by_active_context_types(index):
    chunks = [
        Chunk(id="past_ticket::PIG-1", text="alpha issue text", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-1"}),
        Chunk(id="design_doc::basic", text="alpha doc text", context_type=ContextType.DESIGN_DOCS,
              metadata={"source": "basic.xml"}),
    ]
    index.add_chunks(chunks, embed_fn=_fake_embed)

    result = index.dense_query(_fake_embed(["alpha query"])[0], active=(ContextType.PAST_TICKETS,), top_k=5)
    assert result["ids"][0] == ["past_ticket::PIG-1::0"]


def test_dense_query_excludes_own_issue_id(index):
    chunks = [
        Chunk(id="past_ticket::PIG-1", text="alpha issue text", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-1"}),
        Chunk(id="past_ticket::PIG-2", text="alpha other text", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-2"}),
    ]
    index.add_chunks(chunks, embed_fn=_fake_embed)

    result = index.dense_query(
        _fake_embed(["alpha query"])[0], active=(ContextType.PAST_TICKETS,), top_k=5,
        exclude_issue_id="PIG-1",
    )
    assert result["ids"][0] == ["past_ticket::PIG-2::0"]


def test_dense_query_empty_active_returns_no_results(index):
    chunks = [Chunk(id="past_ticket::PIG-1", text="alpha issue text",
                     context_type=ContextType.PAST_TICKETS, metadata={"issue_id": "PIG-1"})]
    index.add_chunks(chunks, embed_fn=_fake_embed)

    result = index.dense_query(_fake_embed(["alpha"])[0], active=(), top_k=5)
    assert result["ids"] == [[]]


def test_codebase_summary_coverage_and_gate(index):
    chunks = [
        Chunk(id="codebase_summary::Foo.java", text="alpha summary", context_type=ContextType.CODEBASE_SUMMARIES,
              metadata={"file_path": "Foo.java"}),
        Chunk(id="codebase_summary::Bar.java", text="beta summary", context_type=ContextType.CODEBASE_SUMMARIES,
              metadata={"file_path": "Bar.java"}),
    ]
    index.add_chunks(chunks, embed_fn=_fake_embed)

    covered, total = index.codebase_summary_coverage(total_files=3)
    assert (covered, total) == (2, 3)

    with pytest.raises(RuntimeError, match=r"2/3"):
        index.assert_codebase_summaries_complete(total_files=3)

    index.assert_codebase_summaries_complete(total_files=2)  # does not raise: fully covered
