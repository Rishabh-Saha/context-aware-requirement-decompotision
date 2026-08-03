"""Reciprocal Rank Fusion (Cormack et al., 2009), used to fuse the dense and lexical ranked lists
(proposal Section 7.2). RRF combines ranks rather than raw scores, so it is robust to the very
different score distributions dense and lexical retrieval produce. Fusion constant defaults to 50,
the value fixed in the proposal.
"""

from __future__ import annotations

from typing import Hashable, Sequence

RRF_K = 50


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[Hashable]], k: int = RRF_K
) -> list[Hashable]:
    """Fuse ranked lists into one ranking. Each input list is ordered best-first. An item's fused
    score is the sum over lists of 1 / (k + rank), rank being 1-based. Returns items ordered by
    fused score descending; ties keep first-seen order for determinism."""
    scores: dict[Hashable, float] = {}
    first_seen: dict[Hashable, int] = {}
    seq = 0
    for lst in ranked_lists:
        for rank, item in enumerate(lst, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            if item not in first_seen:
                first_seen[item] = seq
                seq += 1
    return sorted(scores, key=lambda it: (-scores[it], first_seen[it]))
