from src.analysis.stats import (
    holm_bonferroni,
    rank_biserial_from_pairs,
    wilcoxon_signed_rank,
)


def test_holm_bonferroni_orders_and_flags():
    res = holm_bonferroni([0.01, 0.04, 0.03], alpha=0.05)
    by_idx = {r["index"]: r for r in res}
    # smallest p gets multiplied by m=3
    assert abs(by_idx[0]["adjusted_p"] - 0.03) < 1e-9
    assert by_idx[0]["reject"] is True
    # adjusted p-values are monotonic non-decreasing in original-p order
    assert by_idx[2]["adjusted_p"] <= by_idx[1]["adjusted_p"] + 1e-9


def test_rank_biserial_direction():
    x = [5, 6, 7, 8]
    y = [1, 2, 3, 4]
    assert rank_biserial_from_pairs(x, y) == 1.0        # x strictly dominates
    assert rank_biserial_from_pairs(y, x) == -1.0


def test_wilcoxon_all_ties():
    r = wilcoxon_signed_rank([3, 3, 3], [3, 3, 3])
    assert r.n == 0
    assert r.p_value == 1.0
