"""The six ablation conditions (proposal Section 7.3) and the four retrievable context types.

Each condition is defined purely by which context types retrieval is allowed to draw from, which
is what makes the ablation clean: the same retrieval call runs with different metadata filters, so
observed differences trace to context-type composition rather than pipeline changes.
"""

from __future__ import annotations

from enum import Enum


class ContextType(str, Enum):
    PAST_TICKETS = "past_tickets"
    DESIGN_DOCS = "design_documents"
    CODING_CONVENTIONS = "coding_conventions"
    CODEBASE_SUMMARIES = "codebase_summaries"


ALL_CONTEXT_TYPES: tuple[ContextType, ...] = tuple(ContextType)


class Condition(str, Enum):
    VANILLA = "vanilla"
    FULL_RAG = "full_rag"
    NO_PAST_TICKETS = "full_rag_minus_past_tickets"
    NO_DESIGN_DOCS = "full_rag_minus_design_documents"
    NO_CODING_CONVENTIONS = "full_rag_minus_coding_conventions"
    NO_CODEBASE_SUMMARIES = "full_rag_minus_codebase_summaries"


# Which context types each condition retrieves over. VANILLA retrieves nothing.
CONDITION_CONTEXTS: dict[Condition, tuple[ContextType, ...]] = {
    Condition.VANILLA: (),
    Condition.FULL_RAG: ALL_CONTEXT_TYPES,
    Condition.NO_PAST_TICKETS: tuple(c for c in ALL_CONTEXT_TYPES if c is not ContextType.PAST_TICKETS),
    Condition.NO_DESIGN_DOCS: tuple(c for c in ALL_CONTEXT_TYPES if c is not ContextType.DESIGN_DOCS),
    Condition.NO_CODING_CONVENTIONS: tuple(c for c in ALL_CONTEXT_TYPES if c is not ContextType.CODING_CONVENTIONS),
    Condition.NO_CODEBASE_SUMMARIES: tuple(c for c in ALL_CONTEXT_TYPES if c is not ContextType.CODEBASE_SUMMARIES),
}

LEAVE_ONE_OUT: tuple[Condition, ...] = (
    Condition.NO_PAST_TICKETS,
    Condition.NO_DESIGN_DOCS,
    Condition.NO_CODING_CONVENTIONS,
    Condition.NO_CODEBASE_SUMMARIES,
)


def active_contexts(condition: Condition) -> tuple[ContextType, ...]:
    return CONDITION_CONTEXTS[condition]
