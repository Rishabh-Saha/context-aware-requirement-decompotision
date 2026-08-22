"""Layer 3: run the pairwise judge over an existing generation run (proposal Section 7.4).

This is a separate pass over the archived decompositions rather than part of run_experiment.py, so
the judge can be re-run, resumed, or pointed at a different generation run without touching a single
generation. It reads `data/runs/<run-id>/`, judges the seven comparison types per requirement in
both presentation orders, and reconciles each pair.

Three things this script exists to guarantee:

Different model family. The judge comes from config `llm.judge` and the generator is read back from
the generation run's own manifest. If the two share a provider the run refuses to start, because a
model judging its own family is the self-enhancement bias the pairwise design is meant to avoid.

Blindness. The judge sees a requirement and two anonymous outputs. Condition names, the word
reference, run ids and file names never enter the prompt, and both sides go through the same
renderer, so nothing in the presentation identifies which arm produced which side.

Positional bias control. Every comparison type is judged twice with the sides swapped. Agreement
across the two orders yields a winner; disagreement is recorded as positional_inconsistent with a
null winner rather than being broken by a coin flip. The inconsistency rate is itself a reportable
number, so it is tallied at the end of the run.

Usage:
    python scripts/run_judge.py --run-id 20260814T033139Z --limit 1   # smoke test, 7 comparisons
    python scripts/run_judge.py --run-id 20260814T033139Z            # the full 140
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()   # the judge call needs the provider key

import yaml  # noqa: E402

from src.eval.comparisons import build_ordered_comparisons, reconcile  # noqa: E402
from src.eval.judge import CRITERIA, judge_pair, load_template  # noqa: E402
# resolve_side is the only renderer this script calls on purpose: it dispatches between a condition
# and the reference sentinel, so both sides of every comparison go through one path rather than this
# script deciding which renderer a side deserves. scrub_artefact is not called here; it is re-exported
# because tests/test_run_judge.py asserts the scrubbing behaviour through this module, which is where
# the blinding guarantee is claimed.
from src.eval.rendering import requirement_text, resolve_side, scrub_artefact  # noqa: E402,F401
from src.utils.io import read_jsonl, write_json  # noqa: E402

DEFAULT_CONFIG = "config/config.yaml"
DEFAULT_FROZEN = "data/frozen/requirements.json"
DEFAULT_RUNS_DIR = "data/runs"
DEFAULT_PROMPT = "prompts/judge_pairwise.txt"
JUDGE_SUBDIR = "judge"


# ---------------------------------------------------------------- loading the generation run

def frozen_requirements(path: str | Path) -> list[dict]:
    """The frozen requirements, without the _meta provenance entry the freeze script prepends."""
    records = json.loads(Path(path).read_text())
    return [r for r in records if isinstance(r, dict) and r.get("issue_key")]


# ---------------------------------------------------------------- judging and reconciling

def side_of(verdict_choice: str, a_side: str, b_side: str) -> str:
    """Map a judge answer ("A"/"B") back to the side it actually refers to.

    This is the whole point of judging both orders: in the BA presentation "A" means the side that
    was "B" in the AB presentation, so winners have to be translated out of positional labels before
    the two orders can be compared at all.
    """
    return a_side if verdict_choice == "A" else b_side


def make_judge(judge_cfg: dict):
    """Judge client from config. Provider and temperature are passed explicitly and recorded in the
    manifest, since the judge configuration is part of what the Layer 3 results mean."""
    provider = judge_cfg["provider"].lower()
    model = judge_cfg["model"]
    temperature = float(judge_cfg["temperature"])
    if provider == "anthropic":
        from src.llm.anthropic_client import AnthropicClient
        return AnthropicClient(model=model, temperature=temperature)
    if provider == "openai":
        from src.llm.openai_client import OpenAIClient
        return OpenAIClient(model=model, temperature=temperature)
    raise ValueError(f"unsupported judge provider: {provider!r}")


def assert_different_family(judge_cfg: dict, generator: dict) -> None:
    """Refuse to run a judge from the generator's family.

    Provider is a coarse proxy for family, but it is the check that catches the realistic mistake:
    someone edits config to point the judge at whatever key happens to be set. This is a hard stop
    rather than a warning because the resulting numbers would be unreportable, and a warning in a
    long run scrolls past unread.
    """
    if judge_cfg["provider"].lower() == str(generator.get("provider", "")).lower():
        raise SystemExit(
            f"judge provider {judge_cfg['provider']!r} matches the generator provider "
            f"{generator.get('provider')!r}. Layer 3 requires a judge from a different model family "
            "to avoid self-enhancement bias. Fix llm.judge in config before running."
        )


def existing_judged_keys(path: Path) -> set[tuple[str, str, str]]:
    """(issue_key, left, right) triples already reconciled, so a resumed pass never re-pays for a
    comparison that is on disk."""
    if not path.exists():
        return set()
    return {(row["issue_key"], row["left"], row["right"]) for row in read_jsonl(path)
            if "issue_key" in row and "left" in row and "right" in row}


def append_jsonl(path: Path, row: dict) -> None:
    """Append one row immediately. A judge pass is long and paid-for, so an interruption must keep
    every verdict it already has."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prompt_fingerprint(template: str) -> str:
    """Short hash of the judge template text.

    Stamped on every verdict rather than only in the manifest, because a template can be revised
    between a first pass and a resume. The manifest would then record only the latest wording while
    most verdicts came from the earlier one, and nothing on disk would say which was which.
    """
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:12]


def raw_row(run_id: str, issue_key: str, ordered, verdict, judge: dict,
            prompt_sha: str = "") -> dict:
    """One ordered verdict exactly as the judge gave it, plus the positional-to-side translation.

    Both are stored: the raw A/B answers make the reconciliation auditable and would allow a
    positional-bias analysis on its own, and the translated side names are what reconciliation
    actually consumes.
    """
    return {
        "run_id": run_id,
        "issue_key": issue_key,
        "presentation": ordered.presentation,
        "shown_a": ordered.a,
        "shown_b": ordered.b,
        "sub_question": ordered.sub_question,
        "judge_model": judge["model"],
        "judge_temperature": judge["temperature"],
        "prompt_sha256": prompt_sha,
        "judged_at": datetime.now(timezone.utc).isoformat(),
        "raw_winner": verdict.winner,
        "raw_per_criterion": verdict.per_criterion,
        "winner_side": side_of(verdict.winner, ordered.a, ordered.b),
        "per_criterion_side": {
            criterion: side_of(choice, ordered.a, ordered.b)
            for criterion, choice in verdict.per_criterion.items()
        },
        "rationale": verdict.rationale,
    }


def reconciled_row(run_id: str, issue_key: str, left: str, right: str, sub_question: str,
                   ab_row: dict, ba_row: dict, judge: dict) -> dict:
    """One comparison type, both orders reconciled.

    The overall winner and each criterion are reconciled independently, because a judge can be
    positionally stable on some criteria and not others, and collapsing that to a single flag would
    throw away signal the analysis may want. `winner` is null exactly when the two orders disagreed.
    """
    per_criterion: dict[str, str | None] = {}
    for criterion in CRITERIA:
        per_criterion[criterion] = reconcile(
            ab_row["per_criterion_side"][criterion],
            ba_row["per_criterion_side"][criterion],
            left, right,
        )
    winner = reconcile(ab_row["winner_side"], ba_row["winner_side"], left, right)
    return {
        "run_id": run_id,
        "issue_key": issue_key,
        "left": left,
        "right": right,
        "sub_question": sub_question,
        "judge_model": judge["model"],
        "judge_temperature": judge["temperature"],
        "judged_at": datetime.now(timezone.utc).isoformat(),
        "winner": winner,
        "positional_inconsistent": winner is None,
        "per_criterion_winner": per_criterion,
        "per_criterion_inconsistent": [c for c, w in per_criterion.items() if w is None],
        "ab_winner_side": ab_row["winner_side"],
        "ba_winner_side": ba_row["winner_side"],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 3 pairwise judge over an existing generation run.")
    p.add_argument("--run-id", required=True, help="generation run directory to score")
    p.add_argument("--config", default=DEFAULT_CONFIG)
    p.add_argument("--frozen", default=DEFAULT_FROZEN)
    p.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR)
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--limit", type=int, default=None,
                   help="only the first N frozen requirements, for a smoke test before the full pass")
    args = p.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text())
    judge_cfg = cfg["llm"]["judge"]
    criteria = tuple(cfg["eval"]["judge"]["criteria"])
    if criteria != CRITERIA:
        raise SystemExit(f"config judge criteria {criteria} do not match the parser's {CRITERIA}")

    run_dir = Path(args.runs_dir) / args.run_id
    if not run_dir.is_dir():
        raise SystemExit(f"no generation run at {run_dir}")
    gen_manifest = json.loads((run_dir / "manifest.json").read_text())
    generator = gen_manifest.get("generator", {})
    assert_different_family(judge_cfg, generator)

    judge = {
        "provider": judge_cfg["provider"],
        "model": judge_cfg["model"],
        "temperature": float(judge_cfg["temperature"]),
    }
    llm = make_judge(judge_cfg)
    template = load_template(args.prompt)
    prompt_sha = prompt_fingerprint(template)

    requirements = frozen_requirements(args.frozen)
    if args.limit is not None:
        requirements = requirements[:args.limit]
    # Only requirements the generation run actually covered can be judged.
    covered = set(gen_manifest.get("requirements", []))
    requirements = [r for r in requirements if r["issue_key"] in covered]

    out_dir = run_dir / JUDGE_SUBDIR
    judgments_path = out_dir / "judgments.jsonl"
    raw_path = out_dir / "judgments_raw.jsonl"
    failures_path = out_dir / "failures.jsonl"

    # Seven comparison types per requirement, each judged in both orders.
    types_per_requirement = len(build_ordered_comparisons("_")) // 2
    total = len(requirements) * types_per_requirement

    write_json(out_dir / "manifest.json", {
        "judge_started_at": datetime.now(timezone.utc).isoformat(),
        "generation_run_id": args.run_id,
        "generator": generator,
        "judge": judge,
        "criteria": list(CRITERIA),
        "prompt_file": args.prompt,
        "prompt_sha256": prompt_sha,
        "requirements": [r["issue_key"] for r in requirements],
        "n_requirements": len(requirements),
        "comparison_types_per_requirement": types_per_requirement,
        "n_comparisons": total,
        "n_ordered_judgements": total * 2,
        "limit": args.limit,
        "blind": True,
        "notes": (
            "Both presentation orders are judged and reconciled; winner is null where they "
            "disagree. The judge prompt carries only OUTPUT A and OUTPUT B, with no condition or "
            "reference labels. Known limitation: in the SQ3 comparisons the reference side is human "
            "prose and the model side is a generated decomposition, so a common plain-text "
            "renderer, plus the scrubbing of commit trailers and issue-key subject prefixes, "
            "reduces but cannot remove the difference between them."
        ),
    })

    done_keys = existing_judged_keys(judgments_path)
    print(f"\njudging generation run {args.run_id}: {len(requirements)} requirement(s) x "
          f"{types_per_requirement} comparisons = {total}, judge {judge['model']} @ temperature "
          f"{judge['temperature']} (generator was {generator.get('model')})")
    print(f"writing to {out_dir}\n")

    judged = skipped = failed = inconsistent = 0
    done = 0

    for requirement in requirements:
        issue_key = requirement["issue_key"]
        ordered = build_ordered_comparisons(issue_key)
        # The two orders of one comparison type sit next to each other, so pairing them is just a
        # walk in twos over the list comparisons.py already builds.
        for ab, ba in zip(ordered[::2], ordered[1::2]):
            done += 1
            left, right = ab.a, ab.b
            label = f"[{done}/{total}] {issue_key} {left} vs {right} ({ab.sub_question})"

            if (issue_key, left, right) in done_keys:
                skipped += 1
                print(f"{label} skip (already judged)")
                continue

            try:
                requirement_prompt = requirement_text(requirement)
                sides = {
                    left: resolve_side(left, requirement, run_dir),
                    right: resolve_side(right, requirement, run_dir),
                }
                rows = {}
                for oc in (ab, ba):
                    verdict = judge_pair(
                        sides[oc.a], sides[oc.b], requirement_prompt, llm, template=template
                    )
                    rows[oc.presentation] = raw_row(args.run_id, issue_key, oc, verdict, judge,
                                                    prompt_sha)
            except Exception as exc:   # noqa: BLE001
                # One bad comparison must not cost the rest of the pass. Nothing is written to
                # judgments.jsonl for it, so a later resume retries exactly this comparison.
                failed += 1
                append_jsonl(failures_path, {
                    "run_id": args.run_id,
                    "issue_key": issue_key,
                    "left": left,
                    "right": right,
                    "sub_question": ab.sub_question,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"{label} FAIL {type(exc).__name__}: {exc}")
                continue

            for presentation in ("AB", "BA"):
                append_jsonl(raw_path, rows[presentation])
            row = reconciled_row(args.run_id, issue_key, left, right, ab.sub_question,
                                 rows["AB"], rows["BA"], judge)
            append_jsonl(judgments_path, row)
            done_keys.add((issue_key, left, right))
            judged += 1
            if row["positional_inconsistent"]:
                inconsistent += 1
                print(f"{label} positional_inconsistent (orders disagreed)")
            else:
                print(f"{label} winner {row['winner']}")

    rate = f"{inconsistent / judged:.1%}" if judged else "n/a"
    print(f"\n== judge pass over {args.run_id} ==")
    print(f"  judged                : {judged}")
    print(f"  skipped (resume)      : {skipped}")
    print(f"  failed                : {failed}")
    print(f"  positional_inconsistent: {inconsistent} of {judged} judged ({rate})")
    print(f"  reconciled rows: {len(done_keys)}/{total} -> {judgments_path}")
    if failed:
        print(f"  {failed} comparison(s) failed, see {failures_path}. Re-run the same command to "
              "retry only those.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
