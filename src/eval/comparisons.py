"""Layer 3 comparison-pair generation (proposal Section 7.4).

The judge does not score the full pairwise matrix. Per requirement it runs exactly the seven
comparisons that bear on the sub-questions, each presented in both orders and reconciled to
neutralise positional bias. This module builds that fixed set deterministically; the judge call
itself lives in judge.py.

    SQ1 (4): each leave-one-out condition vs full RAG
    SQ2 (1): vanilla vs full RAG
    SQ3 (2): full RAG vs reference, vanilla vs reference
"""

from __future__ import annotations

from dataclasses import dataclass

from src.conditions import Condition, LEAVE_ONE_OUT

REFERENCE = "reference"   # sentinel for the human-authored SEOSS artefact


@dataclass(frozen=True)
class ComparisonType:
    left: str            # Condition value or REFERENCE
    right: str
    sub_question: str    # "SQ1" | "SQ2" | "SQ3"


def comparison_types() -> list[ComparisonType]:
    types: list[ComparisonType] = []
    for loo in LEAVE_ONE_OUT:
        types.append(ComparisonType(loo.value, Condition.FULL_RAG.value, "SQ1"))
    types.append(ComparisonType(Condition.VANILLA.value, Condition.FULL_RAG.value, "SQ2"))
    types.append(ComparisonType(Condition.FULL_RAG.value, REFERENCE, "SQ3"))
    types.append(ComparisonType(Condition.VANILLA.value, REFERENCE, "SQ3"))
    return types


@dataclass(frozen=True)
class OrderedComparison:
    requirement_id: str
    a: str               # shown first to the judge
    b: str               # shown second
    sub_question: str
    presentation: str    # "AB" or "BA" (the swapped order of the same comparison type)


def build_ordered_comparisons(requirement_id: str) -> list[OrderedComparison]:
    """Both presentation orders for all seven comparison types = 14 ordered judgements."""
    out: list[OrderedComparison] = []
    for ct in comparison_types():
        out.append(OrderedComparison(requirement_id, ct.left, ct.right, ct.sub_question, "AB"))
        out.append(OrderedComparison(requirement_id, ct.right, ct.left, ct.sub_question, "BA"))
    return out


def reconcile(ab_winner: str, ba_winner: str, left: str, right: str) -> str | None:
    """Reconcile the two presentation orders for one comparison type. If both orders agree on the
    same underlying option, that option wins. If they disagree (positional bias), return None to
    mark it a tie/inconsistent, to be handled downstream (e.g. dropped or counted as a draw)."""
    if ab_winner == ba_winner:
        return ab_winner
    return None
