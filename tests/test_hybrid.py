"""Tests for hybrid retrieval against a real (temp-dir) ChromaDB collection, with the same
deterministic fake embeddings used in test_index.py so nothing here calls OpenAI. The containment
link that defines a requirement's sub-tasks comes from a fixture SEOSS database built with the real
schema, as in test_seoss_loader.py.
"""

import sqlite3
from pathlib import Path

import pytest

from src.conditions import ALL_CONTEXT_TYPES, ContextType
from src.data.seoss_loader import SeossLoader
from src.retrieval.hybrid import hybrid_retrieve, lexical_rank, self_exclusion_ids
from src.retrieval.index import ContextIndex
from src.retrieval.sources import Chunk

pytest.importorskip("chromadb")

SCHEMA = """
CREATE TABLE issue (issue_id text NOT NULL UNIQUE, type text, created_date text, resolved_date text, summary text, description text, status text, resolution text);
CREATE TABLE issue_link (source_issue_id text NOT NULL, target_issue_id text NOT NULL, name text, outward_label text, is_containment integer);
"""


def _fake_embed(texts: list[str]) -> list[list[float]]:
    # Same trick as test_index.py: "alpha" texts point one way, everything else the other, so the
    # dense channel's ordering is predictable without a real embedding model.
    return [[1.0, 0.0] if "alpha" in t else [0.0, 1.0] for t in texts]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "pig.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    # PIG-1 contains PIG-1a (its human decomposition); PIG-9 is merely related, not contained.
    conn.execute("INSERT INTO issue_link VALUES (?,?,?,?,?)", ("PIG-1", "PIG-1a", "sub", "contains", 1))
    conn.execute("INSERT INTO issue_link VALUES (?,?,?,?,?)", ("PIG-1", "PIG-9", "rel", "relates to", 0))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def index(tmp_path: Path) -> ContextIndex:
    return ContextIndex(collection_name="hybrid_test", persist_dir=str(tmp_path / "chroma"))


def _seed(index: ContextIndex) -> None:
    chunks = [
        Chunk(id="past_ticket::PIG-1", text="alpha csv storage loader", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-1"}),
        Chunk(id="past_ticket::PIG-1a", text="alpha csv storage writer subtask", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-1a"}),
        Chunk(id="past_ticket::PIG-2", text="alpha csv parser work", context_type=ContextType.PAST_TICKETS,
              metadata={"issue_id": "PIG-2"}),
        Chunk(id="design_doc::basic", text="alpha csv load and store docs", context_type=ContextType.DESIGN_DOCS,
              metadata={"source": "basic.xml"}),
        Chunk(id="codebase_summary::CSVStorage.java", text="beta unrelated summary",
              context_type=ContextType.CODEBASE_SUMMARIES, metadata={"file_path": "CSVStorage.java"}),
    ]
    index.add_chunks(chunks, embed_fn=_fake_embed)


def test_self_exclusion_ids_is_containment_only(db):
    with SeossLoader(db) as loader:
        assert self_exclusion_ids(loader, "PIG-1") == {"PIG-1", "PIG-1a"}   # PIG-9 is not contained


def test_fused_result_excludes_own_issue_and_containment_subtasks(db, index):
    """The invariant: the requirement's own ticket and its sub-tasks must not survive either
    channel. Both are strong lexical matches for this query, so a fusion that only filtered the
    dense side would return them."""
    _seed(index)
    with SeossLoader(db) as loader:
        excluded = self_exclusion_ids(loader, "PIG-1")

    got = hybrid_retrieve(
        "alpha csv storage",
        active=ALL_CONTEXT_TYPES,
        index=index,
        embed_fn=_fake_embed,
        exclude_issue_id="PIG-1",
        exclude_issue_ids=excluded - {"PIG-1"},
    )

    ids, _, metadatas = index.chunks_for_types(ALL_CONTEXT_TYPES)
    issue_by_id = {cid: m.get("issue_id") for cid, m in zip(ids, metadatas)}
    assert got, "the query should still retrieve the non-excluded chunks"
    assert all(issue_by_id[cid] not in excluded for cid in got)
    assert "past_ticket::PIG-2::0" in got            # a sibling ticket is still retrievable


def test_lexical_only_match_is_still_excluded(index):
    """PIG-1a is invisible to the dense channel here (its text has no "alpha" token in the fake
    embedding sense of being ranked first) but is a top lexical hit, which is the case the fused
    filter exists for."""
    _seed(index)
    got = hybrid_retrieve(
        "subtask writer", active=(ContextType.PAST_TICKETS,), index=index, embed_fn=_fake_embed,
        exclude_issue_id="PIG-1", exclude_issue_ids=("PIG-1a",),
    )
    assert "past_ticket::PIG-1a::0" not in got


def test_active_types_restrict_the_pool(index):
    _seed(index)
    got = hybrid_retrieve(
        "alpha csv", active=(ContextType.DESIGN_DOCS,), index=index, embed_fn=_fake_embed,
    )
    assert got == ["design_doc::basic::0"]


def test_vanilla_retrieves_nothing(index):
    _seed(index)
    assert hybrid_retrieve("alpha csv", active=(), index=index, embed_fn=_fake_embed) == []


def test_fusion_combines_both_channels_within_top_k(index):
    """Chunks that only one channel finds still make the fused list: the codebase summary is a
    dense match for a "beta" query while the lexical channel favours the token overlap."""
    _seed(index)
    got = hybrid_retrieve(
        "beta csv parser", active=ALL_CONTEXT_TYPES, index=index, embed_fn=_fake_embed, top_k=8,
    )
    assert "codebase_summary::CSVStorage.java::0" in got     # dense side
    assert "past_ticket::PIG-2::0" in got                    # lexical side


def test_top_k_caps_the_result(index):
    _seed(index)
    got = hybrid_retrieve(
        "alpha csv storage", active=ALL_CONTEXT_TYPES, index=index, embed_fn=_fake_embed, top_k=2,
    )
    assert len(got) == 2


def test_lexical_rank_orders_by_overlap():
    ranked = lexical_rank("csv storage loader", {
        "a": "csv storage loader implementation",
        "b": "csv only",
        "c": "nothing in common",
    })
    assert ranked == ["a", "b"]     # "c" scores zero and is dropped
