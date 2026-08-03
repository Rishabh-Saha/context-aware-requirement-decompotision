from src.eval.comparisons import (
    build_ordered_comparisons,
    comparison_types,
    reconcile,
)


def test_seven_comparison_types():
    types = comparison_types()
    assert len(types) == 7
    sqs = [t.sub_question for t in types]
    assert sqs.count("SQ1") == 4
    assert sqs.count("SQ2") == 1
    assert sqs.count("SQ3") == 2


def test_both_orders_generated():
    ordered = build_ordered_comparisons("PIG-123")
    assert len(ordered) == 14                          # 7 types x 2 presentation orders
    assert {o.presentation for o in ordered} == {"AB", "BA"}


def test_reconcile_agreement_and_conflict():
    assert reconcile("full_rag", "full_rag", "vanilla", "full_rag") == "full_rag"
    assert reconcile("vanilla", "full_rag", "vanilla", "full_rag") is None
