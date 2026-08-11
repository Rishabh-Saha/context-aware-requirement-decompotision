"""Eyeball that hybrid retrieval behaves, against the sanity-built index.

Prototypes Option B (per-type retrieval): each active context type is retrieved independently with
its own small budget, then the blocks are combined. hybrid_retrieve already does dense+lexical RRF
within a single type when called with a one-type `active` tuple, so Option B is just calling it
once per active type and concatenating. This is the fastest way to confirm the fix before changing
hybrid.py for real.

What to look for:
  - full_rag now shows ~2 of EACH populated type, not all past_tickets
  - each leave-one-out is missing exactly its dropped type
  - the requirement's own issue id and its containment sub-tasks never appear

Note: codebase_summaries is only partially populated in the sanity build, so it may return fewer
than the budget until the full summary pass is run.

Usage:
    python scripts/sanity_retrieve.py                 # first frozen requirement
    python scripts/sanity_retrieve.py --issue PIG-704
    python scripts/sanity_retrieve.py --per-type 2    # budget per context type
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conditions import Condition, active_contexts, ALL_CONTEXT_TYPES  # noqa: E402
from src.data.seoss_loader import SeossLoader  # noqa: E402
from src.retrieval.hybrid import hybrid_retrieve, self_exclusion_ids  # noqa: E402
from src.retrieval.index import ContextIndex  # noqa: E402

DEFAULT_DB = "data/seoss33/pig.sqlite"
DEFAULT_REPO = "data/repos/pig"
DEFAULT_FROZEN = "data/frozen/requirements.json"

CONDITIONS = [
    Condition.FULL_RAG,
    Condition.NO_PAST_TICKETS,
    Condition.NO_DESIGN_DOCS,
    Condition.NO_CODING_CONVENTIONS,
    Condition.NO_CODEBASE_SUMMARIES,
]


def load_requirements(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text())
    return [r for r in data if isinstance(r, dict) and r.get("issue_key")]


def main() -> int:
    p = argparse.ArgumentParser(description="Sanity-check hybrid retrieval.")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--frozen", default=DEFAULT_FROZEN)
    p.add_argument("--issue", default=None, help="issue_key to test (default: first frozen)")
    p.add_argument("--per-type", type=int, default=2, help="budget per context type (Option B)")
    args = p.parse_args()

    reqs = load_requirements(args.frozen)
    req = next((r for r in reqs if r["issue_key"] == args.issue), None) if args.issue else reqs[0]
    if req is None:
        print(f"issue {args.issue} not in frozen set")
        return 1

    query = f"{req['title']}\n{req['description']}"
    index = ContextIndex()

    # id -> context_type / issue_id lookup, over all four types, for grouping and leak-checking.
    ids, _docs, metas = index.chunks_for_types(ALL_CONTEXT_TYPES)
    ctype_of = {cid: m.get("context_type") for cid, m in zip(ids, metas)}
    issue_of = {cid: m.get("issue_id") for cid, m in zip(ids, metas)}

    with SeossLoader(args.db, args.repo) as loader:
        excluded = self_exclusion_ids(loader, req["issue_key"])

    print(f"Requirement {req['issue_key']}: {req['title']}")
    print(f"Self-exclusion set: {sorted(excluded)}\n")

    for cond in CONDITIONS:
        active = active_contexts(cond)
        # Option B: retrieve each active type independently with its own budget, then combine.
        hits: list[str] = []
        for t in active:
            hits += hybrid_retrieve(
                query, (t,), index, top_k=args.per_type,
                exclude_issue_id=req["issue_key"],
                exclude_issue_ids=excluded - {req["issue_key"]},
            )
        by_type: dict[str, int] = {}
        leaked = []
        for cid in hits:
            by_type[ctype_of.get(cid, "?")] = by_type.get(ctype_of.get(cid, "?"), 0) + 1
            if issue_of.get(cid) in excluded:
                leaked.append(cid)

        dropped = (set(t.value for t in ALL_CONTEXT_TYPES)
                   - set(t.value for t in active)) or {"(none)"}
        print(f"{cond.value}")
        print(f"  dropped type : {', '.join(sorted(dropped))}")
        print(f"  retrieved    : {by_type or '{}'} ({len(hits)} chunks)")
        print(f"  leak check   : {'LEAK ' + str(leaked) if leaked else 'clean'}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())