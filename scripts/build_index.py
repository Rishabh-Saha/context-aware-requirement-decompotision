"""Populate the shared persistent ChromaDB collection with the four context types.

The three cheap types (past_tickets, design_documents, coding_conventions) are always built in
full: they cost nothing but embedding calls, they're static, and every condition needs them.
codebase_summaries is the expensive one, an LLM call per uncached .java file over a 1088-file main
source tree, so it is opt-in. This script prints how many files still need a summary and then
refuses to spend anything unless --confirm-summaries is passed. Already-cached summaries in scope
are indexed either way, since reading the cache is free.

Writes are upserts, so this is safe to re-run. A sanity build followed later by the full summary
pass adds what's missing rather than requiring a rebuild.

Usage:
    python scripts/build_index.py                          # cheap types in full, summary count only
    python scripts/build_index.py --sanity                 # same, summary scope narrowed to the 3
    python scripts/build_index.py --sanity --confirm-summaries    # spends LLM calls, sanity scope
    python scripts/build_index.py --confirm-summaries      # spends LLM calls, all 1088 files

Run from the repo root with the venv active.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repo root importable when run as `python scripts/build_index.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.conditions import ContextType  # noqa: E402
from src.data.frozen import load_frozen_requirements  # noqa: E402
from src.data.seoss_loader import SeossLoader  # noqa: E402
from src.retrieval.index import ContextIndex  # noqa: E402
from src.retrieval.sources import (  # noqa: E402
    codebase_summary_chunks,
    coding_convention_chunks,
    design_document_chunks,
    past_tickets_chunks,
    pending_summary_files,
)
from dotenv import load_dotenv
load_dotenv()

from src.paths import (  # noqa: E402
    DEFAULT_CACHE,
    DEFAULT_COLLECTION,
    DEFAULT_DB,
    DEFAULT_FROZEN,
    DEFAULT_PERSIST,
    DEFAULT_REPO,
    DOCS_SUBPATH,
    SRC_SUBPATH,
)

# The sanity set is the first three frozen requirements, read from the frozen file rather than
# hardcoded so it can never drift from the actual Phase 1 deliverable.
SANITY_N = 3


def sanity_summary_scope(loader: SeossLoader, repo: Path, requirements: list[dict]) -> list[Path]:
    """Main-source .java files touched by the sanity requirements' resolution commits.

    This is the bounded slice of codebase_summaries that makes the sanity run meaningful: the files
    the human resolution actually touched are the ones retrieval has a real chance of needing.
    Paths that no longer exist in the clone are dropped, since a file renamed or deleted since 2009
    cannot be summarized from the working tree.
    """
    wanted: set[str] = set()
    for req in requirements:
        commit = req.get("resolution_commit")
        if not commit:
            continue
        touched = [
            f for f in loader.files_changed(commit)
            if f.endswith(".java") and f.startswith(f"{SRC_SUBPATH}/")
        ]
        present = [f for f in touched if (repo / f).exists()]
        print(f"  {req['issue_key']}: {len(touched)} main-source .java files touched, "
              f"{len(present)} still present in the clone")
        wanted.update(present)
    return sorted(repo / f for f in wanted)


def build_cheap_types(index: ContextIndex, loader: SeossLoader, repo: Path) -> dict[str, int]:
    """past_tickets, design_documents and coding_conventions, always in full."""
    written: dict[str, int] = {}

    print("\n== past_tickets ==")
    written[ContextType.PAST_TICKETS.value] = index.add_chunks(past_tickets_chunks(loader))

    print("\n== design_documents ==")
    docs = design_document_chunks(repo / DOCS_SUBPATH)
    written[ContextType.DESIGN_DOCS.value] = index.add_chunks(docs)

    print("\n== coding_conventions ==")
    conventions = coding_convention_chunks(repo)
    written[ContextType.CODING_CONVENTIONS.value] = index.add_chunks(conventions)

    return written


def build_codebase_summaries(
    index: ContextIndex,
    repo: Path,
    cache_dir: Path,
    scope: list[Path] | None,
    confirm: bool,
    max_files: int | None,
) -> int:
    """Index codebase_summaries over `scope` (None means the full main-source tree).

    Without confirm, no LLM call is made: the pending count is printed and only files that already
    have a cached summary are indexed. That keeps an accidental full sweep impossible while still
    letting a partially-built index grow for free.
    """
    src_root = repo / SRC_SUBPATH
    file_paths = scope if scope is not None else sorted(src_root.rglob("*.java"))
    if max_files is not None:
        file_paths = file_paths[:max_files]
        print(f"--max-summary-files {max_files}: scope truncated to {len(file_paths)} files")

    pending = pending_summary_files(repo, cache_dir, file_paths=file_paths)
    print(f"codebase_summaries scope: {len(file_paths)} file(s), {len(pending)} without a cached "
          f"summary.")

    if pending and not confirm:
        print(f"STOPPING before the summary pass: {len(pending)} uncached file(s) would each cost "
              "one LLM call.")
        print("Re-run with --confirm-summaries to spend them. Files already cached are still "
              "indexed below.")
        file_paths = [p for p in file_paths if p not in set(pending)]
        if not file_paths:
            print("Nothing cached in scope yet, so no codebase_summaries chunks were added.")
            return 0

    chunks = codebase_summary_chunks(
        repo, cache_dir, file_paths=file_paths, confirm=confirm,
    )
    return index.add_chunks(chunks)


def main() -> int:
    p = argparse.ArgumentParser(description="Build the shared context index.")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--frozen", default=DEFAULT_FROZEN)
    p.add_argument("--cache-dir", default=DEFAULT_CACHE)
    p.add_argument("--persist-dir", default=DEFAULT_PERSIST)
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--sanity", action="store_true",
                   help="narrow codebase_summaries to the files touched by the sanity "
                        "requirements' resolution commits; the other three types stay full")
    p.add_argument("--confirm-summaries", action="store_true",
                   help="actually spend the LLM calls for uncached codebase summaries")
    p.add_argument("--max-summary-files", type=int, default=None,
                   help="hard cap on how many files the summary pass may cover, applied to the "
                        "sorted scope so the selection stays deterministic")
    args = p.parse_args()

    repo = Path(args.repo)
    cache_dir = Path(args.cache_dir)
    index = ContextIndex(collection_name=args.collection, persist_dir=args.persist_dir)

    with SeossLoader(args.db, repo) as loader:
        written = build_cheap_types(index, loader, repo)

        print("\n== codebase_summaries ==")
        scope: list[Path] | None = None
        if args.sanity:
            requirements = load_frozen_requirements(args.frozen)[:SANITY_N]
            keys = ", ".join(r["issue_key"] for r in requirements)
            print(f"--sanity: scoping codebase_summaries to the resolution commits of {keys}")
            scope = sanity_summary_scope(loader, repo, requirements)

        written[ContextType.CODEBASE_SUMMARIES.value] = build_codebase_summaries(
            index, repo, cache_dir, scope, args.confirm_summaries, args.max_summary_files,
        )

    total_main_source = len(list((repo / SRC_SUBPATH).rglob("*.java")))
    covered, total = index.codebase_summary_coverage(total_files=total_main_source)

    print("\n== report ==")
    for context_type, count in written.items():
        print(f"  {context_type}: {count} chunk piece(s) upserted")
    print(f"  codebase_summaries coverage: {covered}/{total} main-source files embedded")
    if covered < total:
        print("  The full 120-generation run stays gated on assert_codebase_summaries_complete(); "
              "this index is usable for the sanity run only.")
    else:
        print("  Coverage is complete, so the full run's codebase_summaries gate will pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
