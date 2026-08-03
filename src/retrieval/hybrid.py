"""Hybrid retrieval (proposal Section 7.2): dense (cosine over embeddings) plus lexical
(token-overlap) candidate lists, fused with Reciprocal Rank Fusion, returning the top eight chunks
per query. Ablation conditions are applied by restricting the active context types before fusion.
Fusion is done; dense/lexical candidate generation is scaffolded against the index."""

from __future__ import annotations

import re

from src.conditions import ContextType
from src.retrieval.fusion import RRF_K, reciprocal_rank_fusion

TOP_K = 8


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def lexical_rank(query: str, candidates: dict[str, str]) -> list[str]:
    """Rank candidate ids by token-overlap with the query. `candidates` maps id -> chunk text."""
    q = set(_tokenize(query))
    scored = [(cid, len(q & set(_tokenize(txt)))) for cid, txt in candidates.items()]
    scored = [(cid, s) for cid, s in scored if s > 0]
    return [cid for cid, _ in sorted(scored, key=lambda kv: -kv[1])]


def hybrid_retrieve(query, active: tuple[ContextType, ...], index, top_k: int = TOP_K, k: int = RRF_K) -> list[str]:
    """TODO(rishabh): produce the dense ranked list from index.dense_query(...) and a lexical
    ranked list over the same active-type candidate pool, then fuse. Return the fused top_k ids."""
    raise NotImplementedError("Wire dense_ids + lexical_ids, then: reciprocal_rank_fusion([dense_ids, lexical_ids], k)[:top_k]")
