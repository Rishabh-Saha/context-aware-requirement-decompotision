"""Prompt assembly (proposal Section 7.2).

Retrieved chunks are concatenated into a structured template, each context type rendered under a
clearly labelled section heading, with the requirement (issue title and description) appended last.
Holding this layout fixed across conditions means the only thing that varies between runs is which
context sections are populated, which is what the ablation needs.
"""

from __future__ import annotations

from src.conditions import ContextType

# Human-readable heading per context type, in a stable display order.
_HEADINGS: dict[ContextType, str] = {
    ContextType.PAST_TICKETS: "PAST TICKETS",
    ContextType.DESIGN_DOCS: "DESIGN DOCUMENTS",
    ContextType.CODING_CONVENTIONS: "CODING CONVENTIONS",
    ContextType.CODEBASE_SUMMARIES: "CODEBASE SUMMARIES",
}
_ORDER: tuple[ContextType, ...] = tuple(_HEADINGS)


def build_prompt(
    issue_title: str,
    issue_description: str,
    retrieved: dict[ContextType, list[str]] | None = None,
) -> str:
    """Assemble the user-facing prompt body. `retrieved` maps each active context type to its
    already-retrieved chunk texts. Absent or empty types are omitted, which is exactly how the
    vanilla condition (no retrieval) and the leave-one-out conditions render."""
    retrieved = retrieved or {}
    parts: list[str] = []
    for ctype in _ORDER:
        chunks = [c.strip() for c in retrieved.get(ctype, []) if c and c.strip()]
        if not chunks:
            continue
        parts.append(f"## {_HEADINGS[ctype]}")
        for i, chunk in enumerate(chunks, start=1):
            parts.append(f"[{i}] {chunk}")
        parts.append("")

    parts.append("## REQUIREMENT")
    parts.append(f"Title: {issue_title.strip()}")
    parts.append(f"Description: {issue_description.strip()}")
    return "\n".join(parts).strip()
