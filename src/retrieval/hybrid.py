"""Hybrid retrieval (proposal Section 7.2): dense (cosine over embeddings) plus lexical
(token-overlap) candidate lists, fused with Reciprocal Rank Fusion. Ablation conditions are applied
by restricting the active context types before fusion.

Two entry points. `hybrid_retrieve` is the original global top-k call, one fused pool across all
active types. `retrieve_by_type` is what the pipeline actually runs (docs/DECISION_retrieval_budget
.md, Option B): each active type is retrieved independently with its own small budget, so RRF fuses
dense and lexical within a type rather than across types. The global pool let past_tickets, the type
most similar to a Jira-shaped query, take every slot, which left three of the four leave-one-out
arms removing nothing and made SQ1 unanswerable by construction. Per-type budgets keep every type
represented and every ablation arm measurable.

Self-exclusion is enforced on the fused result, not just on the dense channel. A requirement must
never retrieve its own ticket, and must never retrieve the sub-tasks it contains either: those
sub-tasks are the human decomposition this study is asking the model to produce, so leaking them
into context would hand the answer to the generator and invalidate every condition that includes
past_tickets. ChromaDB's metadata filter carries only the one `$ne` that dense_query applies, and
the lexical channel does not go through that filter at all, so the excluded ids are dropped from
the lexical candidate pool and the fused list is re-checked against chunk metadata before the top_k
cut. Both channels are covered that way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.conditions import ContextType
from src.retrieval.fusion import RRF_K, reciprocal_rank_fusion

TOP_K = 8

# Per-type retrieval budget (docs/DECISION_retrieval_budget.md, Option B). Four active types at two
# chunks each keeps the original top-8 prompt size while guaranteeing every type is represented.
PER_TYPE = 2


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def lexical_rank(query: str, candidates: dict[str, str]) -> list[str]:
    """Rank candidate ids by token-overlap with the query. `candidates` maps id -> chunk text."""
    q = set(_tokenize(query))
    scored = [(cid, len(q & set(_tokenize(txt)))) for cid, txt in candidates.items()]
    scored = [(cid, s) for cid, s in scored if s > 0]
    return [cid for cid, _ in sorted(scored, key=lambda kv: -kv[1])]


def _default_embed_fn(texts: list[str]) -> list[list[float]]:
    from src.llm.openai_client import embed_texts  # lazy: keeps the OpenAI SDK optional at import
    return embed_texts(texts)


def self_exclusion_ids(loader, issue_id: str) -> set[str]:
    """The issue ids a decomposition of `issue_id` must never retrieve: the requirement itself plus
    the sub-tasks it contains. Containment links only, since a non-containment link (duplicates,
    "relates to") is ordinary project context rather than a piece of this requirement's own answer.
    """
    return {issue_id, *loader.linked_issue_ids(issue_id, containment_only=True)}


def hybrid_retrieve(
    query: str,
    active: tuple[ContextType, ...],
    index,
    top_k: int = TOP_K,
    k: int = RRF_K,
    embed_fn=None,
    exclude_issue_id: str | None = None,
    exclude_issue_ids: Iterable[str] = (),
) -> list[str]:
    """Fused top_k chunk ids for `query`, restricted to the active context types.

    `exclude_issue_id` is the requirement's own issue, `exclude_issue_ids` any further ids to keep
    out (its containment sub-tasks, from self_exclusion_ids). Both are honoured on the returned
    list. Vanilla (no active types) retrieves nothing and never touches the collection.
    """
    if not active:
        return []

    excluded = {iid for iid in (exclude_issue_id, *exclude_issue_ids) if iid}

    # One filtered read serves the lexical pool and the metadata check on the fused list, so both
    # channels are scored over exactly the chunks dense retrieval was allowed to see.
    ids, documents, metadatas = index.chunks_for_types(active)
    issue_by_id = {cid: meta.get("issue_id") for cid, meta in zip(ids, metadatas)}
    candidates = {
        cid: doc for cid, doc in zip(ids, documents) if issue_by_id.get(cid) not in excluded
    }

    embed_fn = embed_fn or _default_embed_fn
    query_embedding = embed_fn([query])[0]
    dense = index.dense_query(query_embedding, active, top_k, exclude_issue_id=exclude_issue_id)
    dense_ids = dense["ids"][0] if dense["ids"] else []
    lexical_ids = lexical_rank(query, candidates)

    fused = reciprocal_rank_fusion([dense_ids, lexical_ids], k=k)
    kept = [cid for cid in fused if issue_by_id.get(cid) not in excluded]
    return kept[:top_k]


def retrieve_by_type(
    query: str,
    active: tuple[ContextType, ...],
    index,
    per_type: int = PER_TYPE,
    k: int = RRF_K,
    embed_fn=None,
    exclude_issue_id: str | None = None,
    exclude_issue_ids: Iterable[str] = (),
) -> dict[ContextType, list[str]]:
    """Chunk texts per active context type, at most `per_type` each, ready for build_prompt.

    Each type is retrieved on its own: hybrid_retrieve called with a one-type tuple already does
    dense+lexical RRF inside that type and applies the same self-exclusion, so per-type retrieval is
    one call per type rather than a separate code path. A leave-one-out condition simply arrives
    here with that type missing from `active`, and its block never gets built.

    Types that retrieve nothing are left out of the result rather than mapped to an empty list, so
    the prompt never carries an empty labelled section. Vanilla (empty `active`) returns {}.
    """
    if not active:
        return {}

    # One filtered read covers every type, so the id -> text lookup costs a single get() no matter
    # how many types are active.
    ids, documents, _ = index.chunks_for_types(active)
    text_by_id = dict(zip(ids, documents))

    out: dict[ContextType, list[str]] = {}
    for ctype in active:
        hit_ids = hybrid_retrieve(
            query,
            (ctype,),
            index,
            top_k=per_type,
            k=k,
            embed_fn=embed_fn,
            exclude_issue_id=exclude_issue_id,
            exclude_issue_ids=exclude_issue_ids,
        )
        texts = [text_by_id[cid] for cid in hit_ids if cid in text_by_id]
        if texts:
            out[ctype] = texts
    return out
