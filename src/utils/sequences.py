"""Order-preserving sequence helpers.

Four places built the same dedupe by hand, two of them in one file: the commit window unions
ancestors with descendants, from_anchors unions several windows, and commit resolution flattens
Jira-key matches and then returns candidate shas. Each spelled it slightly differently, one with a
dict and setdefault, one with a set and an append, which made four identical intentions look like
four different ones.

Order is load-bearing at every call site, which is why none of them reached for `set()`. The commit
window is ordered nearest-anchor-first, and Layer 2 reads the refs in that order; commit resolution
returns candidates most-specific-first. A set would scramble both and the damage would be invisible,
since the result would still contain the right elements.
"""

from __future__ import annotations

from typing import Callable, Hashable, Iterable, TypeVar

T = TypeVar("T")


def dedupe(items: Iterable[T], key: Callable[[T], Hashable] | None = None) -> list[T]:
    """Items with duplicates dropped, first occurrence winning and input order preserved.

    `key` picks the identity to compare on, for callers holding objects rather than the values they
    are deduplicating by. Without it, items are compared directly and must be hashable.
    """
    seen: set[Hashable] = set()
    out: list[T] = []
    for item in items:
        identity = key(item) if key is not None else item
        if identity not in seen:
            seen.add(identity)
            out.append(item)
    return out
