from src.retrieval.fusion import reciprocal_rank_fusion


def test_rrf_rewards_agreement():
    # 'b' appears high in both lists, so it should win the fusion.
    dense = ["a", "b", "c"]
    lexical = ["b", "d", "a"]
    fused = reciprocal_rank_fusion([dense, lexical], k=50)
    assert fused[0] == "b"
    assert set(fused) == {"a", "b", "c", "d"}


def test_rrf_single_list_preserves_order():
    assert reciprocal_rank_fusion([["x", "y", "z"]], k=50) == ["x", "y", "z"]


def test_rrf_tie_breaks_by_first_seen():
    # Two items with identical fused scores keep first-seen order deterministically.
    fused = reciprocal_rank_fusion([["p", "q"], ["p", "q"]], k=50)
    assert fused == ["p", "q"]
