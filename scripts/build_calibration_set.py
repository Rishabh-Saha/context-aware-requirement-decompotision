"""Layer 4 step one: draw a blinded calibration sample from a completed judge pass.

Layer 4 asks whether the LLM judge agrees with the researcher well enough for Layer 3 to count as a
primary quality signal. That question only has an answer if the researcher rated the same stimulus
the judge rated, without knowing what the judge said or which arm produced which side. This script
builds that rating task and keeps the answers away from it.

How blinding is enforced:

Same renderer. Both sides go through src/eval/rendering, the module the judge itself uses, so the
sheet is not a reconstruction of what the judge saw but literally the same text.

Fresh randomisation. Which side becomes sheet-A is drawn here, independently of the presentation
order the judge saw, so the rater's A and B carry no trace of Layer 3.

Separated key. The sheet and the ratings CSV contain no condition names, no reference label and no
judge verdict. All of that lives in key.json, which the scoring script reads and the rater must not
open until the CSV is filled.

Sampling is stratified in proportion to the comparison design, 4:1:2 across SQ1, SQ2 and SQ3, so
kappa reflects the judge's reliability over the mix of comparisons the analysis actually uses rather
than over-weighting the single SQ2 comparison type. Decided comparisons are preferred: where the two
presentation orders disagreed, the judge has no reconciled position to agree or disagree with.

Usage:
    python scripts/build_calibration_set.py --run-id 20260814T033139Z
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.eval.judge import CRITERIA  # noqa: E402
from src.eval.rendering import requirement_text, resolve_side  # noqa: E402
from src.utils.io import read_jsonl, write_json  # noqa: E402

DEFAULT_FROZEN = "data/frozen/requirements.json"
DEFAULT_RUNS_DIR = "data/runs"
CALIBRATION_SUBDIR = "calibration"
JUDGE_SUBDIR = "judge"

DEFAULT_SEED = 20260814
DEFAULT_N = 20

# Proportional to the seven comparison types (4 SQ1, 1 SQ2, 2 SQ3). Computed by largest remainder
# from n rather than hard-coded, so a different --n still splits in the design's proportions.
DESIGN_WEIGHTS = {"SQ1": 4, "SQ2": 1, "SQ3": 2}

# The extra rating column beyond the five criteria. The reconciled overall winner is what Layer 3
# contributes to the analysis and what the kappa gate governs, so it has to be rateable.
OVERALL = "overall"
RATING_COLUMNS = (*CRITERIA, OVERALL)


def stratum_targets(n: int, weights: dict[str, int]) -> dict[str, int]:
    """Split n across the sub-questions by largest remainder, so the parts sum to exactly n."""
    total = sum(weights.values())
    exact = {sq: n * w / total for sq, w in weights.items()}
    base = {sq: int(v) for sq, v in exact.items()}
    short = n - sum(base.values())
    by_remainder = sorted(exact, key=lambda sq: (-(exact[sq] - base[sq]), sq))
    for sq in by_remainder[:short]:
        base[sq] += 1
    return base


def row_key(row: dict) -> tuple[str, str, str]:
    return (row["issue_key"], row["left"], row["right"])


def spread_sample(rows: list[dict], k: int, rng: random.Random) -> list[dict]:
    """Draw k rows, round-robin across requirements so a stratum does not pile onto a few issues.

    A stratum like SQ1 has four comparison types per requirement, so an unconstrained draw of 11
    could easily land three requirements deep and measure agreement on an unrepresentatively narrow
    slice of the corpus. Cycling issues first spreads the sample before it spends its budget.
    """
    by_issue: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=row_key):
        by_issue[row["issue_key"]].append(row)

    issues = sorted(by_issue)
    rng.shuffle(issues)
    for issue in issues:
        rng.shuffle(by_issue[issue])

    drawn: list[dict] = []
    while len(drawn) < k:
        progressed = False
        for issue in issues:
            if not by_issue[issue]:
                continue
            drawn.append(by_issue[issue].pop())
            progressed = True
            if len(drawn) == k:
                break
        if not progressed:
            break   # pool exhausted; the caller reports the shortfall
    return drawn


def select_pairs(judgments: list[dict], n: int, rng: random.Random) -> tuple[list[dict], dict]:
    """The stratified, decided-preferring sample, plus a provenance record of how it was drawn."""
    targets = stratum_targets(n, DESIGN_WEIGHTS)
    selected: list[dict] = []
    provenance: dict[str, dict] = {}

    for sq in sorted(targets):
        want = targets[sq]
        in_sq = [r for r in judgments if r["sub_question"] == sq]
        decided = [r for r in in_sq if not r["positional_inconsistent"]]
        taken = spread_sample(decided, want, rng)
        # Falling back to positionally inconsistent rows would mean asking the researcher to agree
        # with a judge that has no position, so it happens only if the decided pool runs dry.
        fallback: list[dict] = []
        if len(taken) < want:
            remaining = [r for r in in_sq if r["positional_inconsistent"]]
            fallback = spread_sample(remaining, want - len(taken), rng)
            taken = taken + fallback
        provenance[sq] = {
            "target": want,
            "drawn": len(taken),
            "pool_decided": len(decided),
            "pool_total": len(in_sq),
            "fell_back_to_inconsistent": len(fallback),
        }
        selected.extend(taken)

    # Shuffled so the sheet is not ordered by sub-question. A block of consecutive SQ3 pairs sharing
    # a side would be a structural hint about what is being compared.
    rng.shuffle(selected)
    return selected, provenance


def build_pair(pair_id: str, row: dict, requirement: dict, run_dir: Path,
               rng: random.Random) -> tuple[dict, dict]:
    """One sheet entry and its hidden key.

    The coin flip here is what makes the sheet independent of Layer 3: the judge's own AB and BA
    presentations are already reconciled away, and this draw decides afresh which side the
    researcher sees first.
    """
    left, right = row["left"], row["right"]
    sheet_a, sheet_b = (left, right) if rng.random() < 0.5 else (right, left)

    entry = {
        "pair_id": pair_id,
        "requirement": requirement_text(requirement),
        "output_a": resolve_side(sheet_a, requirement, run_dir),
        "output_b": resolve_side(sheet_b, requirement, run_dir),
    }
    key = {
        "pair_id": pair_id,
        "issue_key": row["issue_key"],
        "sub_question": row["sub_question"],
        "comparison_left": left,
        "comparison_right": right,
        "sheet_a": sheet_a,
        "sheet_b": sheet_b,
        "judge_winner": row["winner"],
        "judge_per_criterion": row["per_criterion_winner"],
        "judge_positional_inconsistent": row["positional_inconsistent"],
    }
    return entry, key


def write_sheet_markdown(path: Path, entries: list[dict]) -> None:
    """The same content as sheet.jsonl, laid out for actually reading while rating."""
    parts = [
        "# Calibration rating sheet",
        "",
        "For each pair, decide whether OUTPUT A or OUTPUT B is better on each criterion, and which "
        "is better overall. Record the answers in calibration_ratings.csv as A or B. Leave a cell "
        "blank only if the two outputs genuinely cannot be separated on that criterion. Blank "
        "cells are dropped from the agreement calculation rather than counted as agreement, so a "
        "blank costs nothing but a guess does.",
        "",
        "Criteria: actionability (can a developer start work directly), completeness (are the "
        "requirement's aspects covered), project_specificity (are references and details grounded "
        "in this project), granularity (are stories sized sensibly), clarity (are stories and "
        "acceptance criteria unambiguous).",
        "",
    ]
    for entry in entries:
        parts += [
            "---",
            "",
            f"## {entry['pair_id']}",
            "",
            "### Requirement",
            "",
            entry["requirement"],
            "",
            "### OUTPUT A",
            "",
            "```",
            entry["output_a"],
            "```",
            "",
            "### OUTPUT B",
            "",
            "```",
            entry["output_b"],
            "```",
            "",
        ]
    path.write_text("\n".join(parts), encoding="utf-8")


def write_ratings_csv(path: Path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pair_id", *RATING_COLUMNS])
        for entry in entries:
            writer.writerow([entry["pair_id"], *([""] * len(RATING_COLUMNS))])


README_TEXT = """# Layer 4 calibration

Rate every pair in `sheet.md` (or `sheet.jsonl`) and record the answers in
`calibration_ratings.csv`, one row per pair, `A` or `B` in each column.

Do not open `key.json` until the CSV is filled. It holds which side is which condition and what the
judge decided. Blind rating is the entire scientific value of Layer 4: an unblinded rating measures
nothing, and there is no way to un-see the key once read.

When the CSV is complete:

    python scripts/score_calibration.py --run-id RUN_ID
"""


def main() -> int:
    p = argparse.ArgumentParser(description="Draw a blinded Layer 4 calibration sample.")
    p.add_argument("--run-id", required=True, help="generation run whose judge pass is scored")
    p.add_argument("--frozen", default=DEFAULT_FROZEN)
    p.add_argument("--runs-dir", default=DEFAULT_RUNS_DIR)
    p.add_argument("--n", type=int, default=DEFAULT_N, help="number of pairs to rate")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help="sampling seed; recorded in the manifest so the draw is reproducible")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing calibration set, discarding any ratings in it")
    args = p.parse_args()

    run_dir = Path(args.runs_dir) / args.run_id
    judgments_path = run_dir / JUDGE_SUBDIR / "judgments.jsonl"
    if not judgments_path.exists():
        raise SystemExit(f"no judge output at {judgments_path}; run scripts/run_judge.py first")

    out_dir = run_dir / CALIBRATION_SUBDIR
    ratings_path = out_dir / "calibration_ratings.csv"
    if ratings_path.exists() and not args.force:
        # Regenerating would silently destroy ratings that cannot be reproduced, since a second
        # blind rating by someone who has already seen the pairs is not blind.
        raise SystemExit(
            f"{ratings_path} already exists. Re-running would discard any ratings in it. Pass "
            "--force only if the existing sheet is genuinely unrated."
        )

    judgments = list(read_jsonl(judgments_path))
    requirements = {r["issue_key"]: r for r in json.loads(Path(args.frozen).read_text())
                    if isinstance(r, dict) and r.get("issue_key")}

    rng = random.Random(args.seed)
    selected, provenance = select_pairs(judgments, args.n, rng)
    if len(selected) < args.n:
        print(f"WARNING: only {len(selected)} of {args.n} pairs available in the judge output.")

    entries: list[dict] = []
    keys: list[dict] = []
    for i, row in enumerate(selected, start=1):
        pair_id = f"pair_{i:02d}"
        requirement = requirements[row["issue_key"]]
        entry, key = build_pair(pair_id, row, requirement, run_dir, rng)
        entries.append(entry)
        keys.append(key)

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "sheet.jsonl", "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    write_sheet_markdown(out_dir / "sheet.md", entries)
    write_ratings_csv(ratings_path, entries)
    write_json(out_dir / "key.json", {k["pair_id"]: k for k in keys})
    (out_dir / "README.md").write_text(README_TEXT, encoding="utf-8")

    write_json(out_dir / "manifest.json", {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "generation_run_id": args.run_id,
        "source": str(judgments_path),
        "n_requested": args.n,
        "n_drawn": len(entries),
        "seed": args.seed,
        "design_weights": DESIGN_WEIGHTS,
        "strata": provenance,
        "rating_columns": list(RATING_COLUMNS),
        "judgments_available": len(judgments),
        "notes": (
            "Sampling is stratified in proportion to the comparison design and prefers decided "
            "comparisons. Which side appears as OUTPUT A was drawn independently of the judge's "
            "presentation order. The sheet and the ratings CSV carry no condition names, no "
            "reference label and no judge verdict; those live only in key.json."
        ),
    })

    print(f"\ncalibration set for {args.run_id}")
    for sq in sorted(provenance):
        p_sq = provenance[sq]
        print(f"  {sq}: {p_sq['drawn']} drawn (target {p_sq['target']}, "
              f"{p_sq['pool_decided']} decided of {p_sq['pool_total']} available)")
    print(f"  {len(entries)} pairs -> {out_dir}")
    print(f"\nRate {out_dir / 'sheet.md'} and fill {ratings_path}.")
    print("Do not open key.json until the CSV is filled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
