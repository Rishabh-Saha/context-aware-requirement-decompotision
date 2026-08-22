"""Run the six ablation conditions across the frozen requirements and apply the diagnostic layers.

Twenty frozen requirements times six conditions is 120 generations, so this script is built around
the assumption that it will be interrupted at least once. Every generation is archived to disk with
the exact prompt that produced it, and a cell whose output file already exists is skipped, so a
crashed run resumes with `--run-id <same id>` without regenerating or re-paying for anything.

Layers 1 (structural) and 2 (file existence) are applied to each decomposition as soon as it lands,
one tidy row per (issue, condition) in diagnostics.jsonl. Both are cheap, deterministic and purely
local, so there is no reason to defer them, and scoring immediately means a crash leaves behind a
partially-scored run rather than a pile of unscored JSON. Layer 3 (the pairwise judge) is
deliberately not wired here: it is a separate pass over these archived outputs.

The generator model and temperature come from config/config.yaml, never from the SDK default, and
both are stamped into the manifest and every output file. The ablation only means something if the
generator is provably identical across all six conditions.

Usage:
    python scripts/run_experiment.py --limit 1        # smoke test, 6 generations
    python scripts/run_experiment.py                  # the full 120
    python scripts/run_experiment.py --run-id 20260813T120000Z   # resume an interrupted run
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()   # retrieval embeds the query and generation calls the provider

import yaml  # noqa: E402

from src.conditions import Condition  # noqa: E402
from src.data.frozen import load_frozen_requirements  # noqa: E402
from src.data.seoss_loader import SeossLoader  # noqa: E402
from src.eval.file_verifier import FileVerifier  # noqa: E402
from src.eval.rendering import cell_stem  # noqa: E402
from src.eval.structural import structural_metrics  # noqa: E402
from src.llm.factory import make_client  # noqa: E402
from src.pipeline.generate import build_condition_prompt, run_condition  # noqa: E402
from src.retrieval.hybrid import PER_TYPE  # noqa: E402
from src.retrieval.index import ContextIndex  # noqa: E402
from src.schema import Decomposition  # noqa: E402
from src.utils.io import append_jsonl, read_jsonl, write_json  # noqa: E402

from src.paths import (  # noqa: E402
    DEFAULT_COLLECTION,
    DEFAULT_CONFIG,
    DEFAULT_DB,
    DEFAULT_FROZEN,
    DEFAULT_PERSIST,
    DEFAULT_REPO,
    DEFAULT_RUNS_DIR,
    SRC_SUBPATH,
)

# Fixed condition order, so the printed progress and the on-disk row order are stable between runs.
CONDITIONS: tuple[Condition, ...] = tuple(Condition)


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cell_paths(run_dir: Path, issue_key: str, condition: Condition) -> tuple[Path, Path]:
    """(decomposition path, prompt path) for one cell of the 20 x 6 grid. The stem comes from
    src.eval.rendering, which is also where the judge and the Layer 4 sheet read these files back
    from, so this writer and those readers cannot disagree about the archive layout."""
    stem = cell_stem(issue_key, condition.value)
    return run_dir / f"{stem}.json", run_dir / f"{stem}.prompt.txt"


def make_llm(llm_cfg: dict):
    """The generator client for this run.

    A named module-level function rather than an alias for make_client, because the resume test
    replaces it wholesale to keep a real provider client from ever being constructed. Collapsing it
    into a direct call would remove that seam and make the test build an OpenAI client.
    """
    return make_client(llm_cfg, role="generator")


def existing_diagnostic_keys(path: Path) -> set[tuple[str, str]]:
    """(issue_key, condition) pairs already scored, so rows are never duplicated on resume."""
    if not path.exists():
        return set()
    return {(row["issue_key"], row["condition"]) for row in read_jsonl(path)
            if "issue_key" in row and "condition" in row}


def source_file_references(decomp: Decomposition) -> list[str]:
    """Every file reference in the decomposition, flat and in story order. Duplicates are kept:
    the Layer 2 rates are per reference made, so citing one hallucinated path in three stories is
    three hallucinated references, which is what the grounding signal should reflect."""
    return [ref for story in decomp.user_stories for ref in story.source_files]


def diagnostics_row(
    run_id: str,
    issue_key: str,
    condition: Condition,
    decomp: Decomposition,
    verifier: FileVerifier | None,
    generator: dict,
    summaries_incomplete: bool,
) -> dict:
    """One self-describing results row: it carries its own run_id, issue_key and condition, so a
    row stays interpretable after rows from several runs are concatenated for analysis.

    Layers 1 and 2 are kept in separate blocks because they answer different questions (shape
    versus grounding) and the proposal reports them separately. `layer2` is null when the
    requirement has no local anchor commits, which is an absent measurement rather than a zero.
    """
    refs = source_file_references(decomp)
    layer2 = None
    if verifier is not None:
        report = verifier.verify(refs)
        layer2 = {
            **report.summary(),
            "unique_references": len(set(refs)),
            "tracked_paths_in_window": verifier.tracked_count,
        }
    return {
        "run_id": run_id,
        "issue_key": issue_key,
        "condition": condition.value,
        "generator_model": generator["model"],
        "generator_temperature": generator["temperature"],
        "summaries_incomplete": summaries_incomplete,
        "layer1": structural_metrics(decomp),
        "layer2": layer2,
    }


def check_summary_coverage(index: ContextIndex, repo: Path, limit: int | None, allow: bool) -> bool:
    """Enforce the codebase_summaries gate, and report whether the run is knowingly incomplete.

    A full run against a partially summarized codebase would invalidate full_rag and three of the
    four leave-one-out arms, so the gate is hard there. With --limit the run is a smoke test, where
    partial coverage is expected and the gate would only get in the way, so coverage is reported as
    a warning instead. Either way the answer is stamped into the manifest and every output file, so
    an incomplete run can never be mistaken later for a clean one.
    """
    total_main_source = len(list((repo / SRC_SUBPATH).rglob("*.java")))
    covered, total = index.codebase_summary_coverage(total_files=total_main_source)
    incomplete = covered < total
    if not incomplete:
        print(f"codebase_summaries coverage: {covered}/{total} files embedded.")
        return False
    if limit is not None:
        print(f"codebase_summaries coverage: {covered}/{total}. --limit is set, so this is a smoke "
              "test and the coverage gate is a warning only.")
        return True
    if allow:
        print(f"codebase_summaries coverage: {covered}/{total}. --allow-incomplete-summaries was "
              "passed, so the run proceeds and every artefact is stamped summaries_incomplete.")
        return True
    # Coverage is short and neither escape hatch applies, so this always raises and the function
    # does not return on this path.
    index.assert_codebase_summaries_complete(total_files=total_main_source)


def build_verifier(repo: Path, requirement: dict, before: int, after: int) -> FileVerifier | None:
    """Layer 2 verifier for one requirement, spanning every local commit its SEOSS anchor resolved
    to. Built once per requirement and reused across its six conditions: each construction walks a
    commit window with a git ls-tree per ref, which is far too expensive to repeat six times."""
    anchors = requirement.get("local_commits") or []
    if not anchors:
        print(f"  WARNING: {requirement['issue_key']} has no local_commits, so Layer 2 is skipped "
              "for it and its rows carry layer2: null")
        return None
    return FileVerifier.from_anchors(repo, anchors, before=before, after=after)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate all decompositions and apply Layers 1 and 2.")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--frozen", default=DEFAULT_FROZEN)
    p.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR)
    p.add_argument("--persist-dir", default=DEFAULT_PERSIST)
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument("--run-id", default=None,
                   help="reuse a previous run id to resume that run in place; default is a new "
                        "UTC timestamp")
    p.add_argument("--limit", type=int, default=None,
                   help="only the first N frozen requirements, for smoke-testing before the full "
                        "120 generations")
    p.add_argument("--per-type", type=int, default=PER_TYPE,
                   help="retrieval budget per context type (Option B)")
    p.add_argument("--allow-incomplete-summaries", action="store_true",
                   help="run the full set even though codebase_summaries coverage is partial; the "
                        "manifest and every output file are stamped summaries_incomplete")
    args = p.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    generator_cfg = cfg["llm"]["generator"]
    verifier_cfg = cfg["eval"]["file_verifier"]
    window_before = int(verifier_cfg["commit_window_before"])
    window_after = int(verifier_cfg["commit_window_after"])

    repo = Path(args.repo)
    run_id = args.run_id or new_run_id()
    run_dir = Path(args.runs_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = run_dir / "diagnostics.jsonl"
    failures_path = run_dir / "failures.jsonl"

    requirements = load_frozen_requirements(args.frozen)
    if args.limit is not None:
        requirements = requirements[:args.limit]
    total_cells = len(requirements) * len(CONDITIONS)

    index = ContextIndex(collection_name=args.collection, persist_dir=args.persist_dir)
    summaries_incomplete = check_summary_coverage(
        index, repo, args.limit, args.allow_incomplete_summaries
    )

    generator = {
        "provider": generator_cfg["provider"],
        "model": generator_cfg["model"],
        "temperature": float(generator_cfg["temperature"]),
    }
    llm = make_llm(generator_cfg)

    write_json(run_dir / "manifest.json", {
        "run_id": run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "generator": generator,
        "summaries_incomplete": summaries_incomplete,
        "conditions": [c.value for c in CONDITIONS],
        "requirements": [r["issue_key"] for r in requirements],
        "n_requirements": len(requirements),
        "n_cells": total_cells,
        "limit": args.limit,
        "per_type": args.per_type,
        "commit_window": {"before": window_before, "after": window_after},
        "paths": {
            "config": args.config, "db": args.db, "repo": args.repo, "frozen": args.frozen,
            "persist_dir": args.persist_dir, "collection": args.collection,
        },
    })

    scored = existing_diagnostic_keys(diagnostics_path)
    print(f"\nrun {run_id}: {len(requirements)} requirement(s) x {len(CONDITIONS)} conditions = "
          f"{total_cells} cells, generator {generator['model']} @ temperature "
          f"{generator['temperature']}")
    print(f"writing to {run_dir}\n")

    generated = reused = failed = 0
    done = 0

    with SeossLoader(args.db, repo) as loader:
        for requirement in requirements:
            issue_key = requirement["issue_key"]
            verifier = build_verifier(repo, requirement, window_before, window_after)

            for condition in CONDITIONS:
                done += 1
                decomp_path, prompt_path = cell_paths(run_dir, issue_key, condition)
                label = f"[{done}/{total_cells}] {issue_key} {condition.value}"

                try:
                    if decomp_path.exists():
                        # Resume: the generation is already paid for, so it is reloaded rather than
                        # repeated, even when the diagnostics row still needs computing.
                        payload = json.loads(decomp_path.read_text())
                        decomp = Decomposition.model_validate(payload["decomposition"])
                        reused += 1
                        status = "skip (already generated)"
                    else:
                        prompt = build_condition_prompt(
                            requirement, condition, index, loader, per_type=args.per_type
                        )
                        decomp = run_condition(
                            requirement, condition, index, loader, llm,
                            per_type=args.per_type, prompt=prompt,
                        )
                        # The prompt is archived before the decomposition, so an artefact on disk
                        # always has the prompt that produced it sitting next to it.
                        prompt_path.parent.mkdir(parents=True, exist_ok=True)
                        prompt_path.write_text(prompt, encoding="utf-8")
                        write_json(decomp_path, {
                            "run_id": run_id,
                            "issue_key": issue_key,
                            "condition": condition.value,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "generator": generator,
                            "summaries_incomplete": summaries_incomplete,
                            "per_type": args.per_type,
                            "prompt_file": prompt_path.name,
                            "decomposition": decomp.model_dump(mode="json"),
                        })
                        generated += 1
                        status = "ok"
                except Exception as exc:   # noqa: BLE001
                    # One bad generation must not cost the other 119. Nothing is written for this
                    # cell, so a later resume retries it.
                    failed += 1
                    append_jsonl(failures_path, {
                        "run_id": run_id,
                        "issue_key": issue_key,
                        "condition": condition.value,
                        "failed_at": datetime.now(timezone.utc).isoformat(),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    print(f"{label} FAIL {type(exc).__name__}: {exc}")
                    continue

                if (issue_key, condition.value) in scored:
                    print(f"{label} {status}, already scored")
                    continue

                append_jsonl(diagnostics_path, diagnostics_row(
                    run_id, issue_key, condition, decomp, verifier, generator,
                    summaries_incomplete,
                ))
                scored.add((issue_key, condition.value))
                print(f"{label} {status}, scored")

    print(f"\n== run {run_id} ==")
    print(f"  generated : {generated}")
    print(f"  reused    : {reused}")
    print(f"  failed    : {failed}")
    print(f"  diagnostics rows: {len(scored)}/{total_cells} -> {diagnostics_path}")
    if summaries_incomplete:
        print("  NOTE: codebase_summaries coverage was incomplete; every artefact is stamped "
              "summaries_incomplete: true and must not be reported as a clean full run.")
    if failed:
        print(f"  {failed} cell(s) failed, see {failures_path}. Re-run with --run-id {run_id} to "
              "retry only those.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
