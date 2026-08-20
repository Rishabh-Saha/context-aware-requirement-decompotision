"""Regenerate every aggregate quoted in Chapters 4-6 from the committed results/ artefacts.

Reads `diagnostics.jsonl` (Layer 1 structural metrics + Layer 2 file-verification verdicts),
`judgments.jsonl` (Layer 3, reconciled pairwise comparisons), `judgments_raw.jsonl` (unreconciled
per-order judge output) and `calibration_result.json` (Layer 4) from the results package, applies
the statistical procedures in `src/analysis/stats.py`, and writes `aggregates.json` plus a printed
table per thesis table.

It calls no external API and needs neither the SEOSS dump nor the Apache Pig clone, so any
reader with the repository alone can regenerate every reported figure from these artefacts.

Usage:
    python scripts/aggregate_results.py --run-id 20260814T033139Z
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analysis.stats import holm_bonferroni, wilcoxon_signed_rank  # noqa: E402
from src.conditions import Condition, LEAVE_ONE_OUT  # noqa: E402
from src.utils.io import read_jsonl, write_json  # noqa: E402

DEFAULT_RESULTS_DIR = "results"

LAYER1_FIELDS = [
    "num_user_stories",
    "well_formedness_rate",
    "avg_acceptance_criteria",
    "file_reference_specificity",
    "inter_story_dependency_rate",
    "dangling_dependency_count",
]
LAYER2_FIELDS = ["real_rate", "ambiguous_rate", "hallucinated_rate"]


def load_diagnostics(results_dir: Path) -> list[dict]:
    return list(read_jsonl(results_dir / "diagnostics.jsonl"))


def load_judgments(results_dir: Path) -> list[dict]:
    return list(read_jsonl(results_dir / "judgments.jsonl"))


def load_judgments_raw(results_dir: Path) -> list[dict]:
    return list(read_jsonl(results_dir / "judgments_raw.jsonl"))


def load_calibration(results_dir: Path) -> dict:
    return json.loads((results_dir / "calibration_result.json").read_text())


def _paired_metric(
    diagnostics: list[dict], left: str, right: str, field: str
) -> tuple[list[float], list[float]]:
    """Pull a Layer 2 field for two conditions, paired by issue_key."""
    by_key_left = {r["issue_key"]: r["layer2"][field] for r in diagnostics if r["condition"] == left}
    by_key_right = {r["issue_key"]: r["layer2"][field] for r in diagnostics if r["condition"] == right}
    shared = sorted(set(by_key_left) & set(by_key_right))
    return [by_key_left[k] for k in shared], [by_key_right[k] for k in shared]


def table_4_1_structural(diagnostics: list[dict]) -> dict:
    """Layer 1 structural metrics by condition, averaged over the 20 requirements."""
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in diagnostics:
        by_condition[row["condition"]].append(row["layer1"])
    out = {}
    for condition, rows in by_condition.items():
        out[condition] = {field: round(mean(r[field] for r in rows), 4) for field in LAYER1_FIELDS}
        out[condition]["n"] = len(rows)
    return out


def table_4_2_layer2(diagnostics: list[dict]) -> dict:
    """Layer 2 verdict distribution by condition, plus the SQ2 test (vanilla vs full RAG) on
    hallucination rate."""
    by_condition: dict[str, list[dict]] = defaultdict(list)
    for row in diagnostics:
        by_condition[row["condition"]].append(row["layer2"])
    distribution = {}
    for condition, rows in by_condition.items():
        distribution[condition] = {field: round(mean(r[field] for r in rows), 4) for field in LAYER2_FIELDS}
        distribution[condition]["n"] = len(rows)

    vanilla, full_rag = _paired_metric(
        diagnostics, Condition.VANILLA.value, Condition.FULL_RAG.value, "hallucinated_rate"
    )
    sq2 = wilcoxon_signed_rank(vanilla, full_rag)
    return {
        "verdict_distribution": distribution,
        "sq2_hallucination_rate_test": {
            "comparison": "vanilla vs full_rag",
            "vanilla_mean": round(mean(vanilla), 4),
            "full_rag_mean": round(mean(full_rag), 4),
            "n": sq2.n,
            "statistic": sq2.statistic,
            "p_value": round(sq2.p_value, 4),
            "rank_biserial": round(sq2.effect_size, 4),
        },
    }


def table_4_3_sq1_hallucination(diagnostics: list[dict]) -> dict:
    """SQ1 leave-one-out comparisons on hallucination rate, Holm-Bonferroni corrected."""
    per_condition: dict[str, dict] = {}
    pvalues: list[float] = []
    order: list[str] = []
    for condition in LEAVE_ONE_OUT:
        loo_vals, full_vals = _paired_metric(
            diagnostics, condition.value, Condition.FULL_RAG.value, "hallucinated_rate"
        )
        result = wilcoxon_signed_rank(loo_vals, full_vals)
        per_condition[condition.value] = {
            "comparison": f"{condition.value} vs full_rag",
            f"{condition.value}_mean": round(mean(loo_vals), 4),
            "full_rag_mean": round(mean(full_vals), 4),
            "n": result.n,
            "statistic": result.statistic,
            "p_value": round(result.p_value, 4),
            "rank_biserial": round(result.effect_size, 4),
        }
        pvalues.append(result.p_value)
        order.append(condition.value)
    corrected = holm_bonferroni(pvalues)
    for condition_value, record in zip(order, corrected):
        per_condition[condition_value]["adjusted_p"] = round(record["adjusted_p"], 4)
        per_condition[condition_value]["reject_at_0.05"] = record["reject"]
    return per_condition


def _sign_test(wins_a: int, wins_b: int) -> dict:
    """Two-sided exact binomial sign test over the decided pairs (ties/positional-inconsistent
    comparisons are excluded, since they carry no winner)."""
    from scipy.stats import binomtest  # lazy

    decided = wins_a + wins_b
    if decided == 0:
        return {"decided": 0, "p_value": 1.0}
    p = binomtest(wins_a, decided, 0.5).pvalue
    return {"decided": decided, "p_value": round(float(p), 6)}


def table_4_4_layer3(judgments: list[dict]) -> dict:
    """Layer 3 pairwise judgement outcomes, one entry per comparison type (7 total: 4 SQ1 + 1 SQ2
    + 2 SQ3). DESCRIPTIVE only per the judge's calibration gate (see Table 4.5)."""
    by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in judgments:
        by_pair[(row["left"], row["right"])].append(row)

    out = {}
    for (left, right), rows in by_pair.items():
        wins_left = sum(1 for r in rows if r["winner"] == left)
        wins_right = sum(1 for r in rows if r["winner"] == right)
        inconsistent = sum(1 for r in rows if r["positional_inconsistent"])
        sign = _sign_test(wins_left, wins_right)
        out[f"{left}_vs_{right}"] = {
            "sub_question": rows[0]["sub_question"],
            "n": len(rows),
            f"wins_{left}": wins_left,
            f"wins_{right}": wins_right,
            "positional_inconsistent": inconsistent,
            "sign_test_decided": sign["decided"],
            "sign_test_p_value": sign["p_value"],
        }
    return out


def positional_inconsistency_rate(judgments_raw: list[dict]) -> dict:
    """Section 4.6: rate at which the two presentation orders disagreed on the winner.

    Recomputed directly from the unreconciled per-order judge output (`judgments_raw.jsonl`)
    rather than trusting the `positional_inconsistent` flag already stored in `judgments.jsonl`,
    so this figure is independently auditable from the raw judge calls.
    """
    by_pair: dict[tuple[str, frozenset], list[dict]] = defaultdict(list)
    for row in judgments_raw:
        key = (row["issue_key"], frozenset({row["shown_a"], row["shown_b"]}))
        by_pair[key].append(row)

    inconsistent = 0
    total = 0
    for rows in by_pair.values():
        total += 1
        winner_sides = {r["winner_side"] for r in rows}
        if len(winner_sides) > 1:
            inconsistent += 1

    return {
        "inconsistent": inconsistent,
        "total": total,
        "rate": round(inconsistent / total, 4) if total else 0.0,
    }


def table_4_5_layer4(calibration: dict) -> dict:
    return {
        "gate_metric": calibration["gate_metric"],
        "threshold": calibration["threshold"],
        "overall": calibration["overall"],
        "pooled_criteria": calibration["pooled_criteria"],
        "per_criterion": calibration["per_criterion"],
    }


def print_table(title: str, data) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="20260814T033139Z")
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    diagnostics = load_diagnostics(results_dir)
    judgments = load_judgments(results_dir)
    judgments_raw = load_judgments_raw(results_dir)
    calibration = load_calibration(results_dir)

    aggregates = {
        "run_id": args.run_id,
        "table_4_1_structural_metrics": table_4_1_structural(diagnostics),
        "table_4_2_layer2_verdicts": table_4_2_layer2(diagnostics),
        "table_4_3_sq1_hallucination_rate": table_4_3_sq1_hallucination(diagnostics),
        "table_4_4_layer3_pairwise": table_4_4_layer3(judgments),
        "table_4_5_layer4_calibration": table_4_5_layer4(calibration),
        "positional_inconsistency_4_6": positional_inconsistency_rate(judgments_raw),
    }

    write_json(results_dir / "aggregates.json", aggregates)

    print_table("Table 4.1 Layer 1 structural metrics by condition", aggregates["table_4_1_structural_metrics"])
    print_table("Table 4.2 Layer 2 verdict distribution and SQ2 test", aggregates["table_4_2_layer2_verdicts"])
    print_table(
        "Table 4.3 SQ1 leave-one-out comparisons on hallucination rate",
        aggregates["table_4_3_sq1_hallucination_rate"],
    )
    print_table("Table 4.4 Layer 3 pairwise judgement outcomes", aggregates["table_4_4_layer3_pairwise"])
    print_table("Table 4.5 Layer 4 researcher-vs-judge agreement", aggregates["table_4_5_layer4_calibration"])
    print_table("Positional inconsistency rate (Section 4.6)", aggregates["positional_inconsistency_4_6"])

    print(f"\nWrote {results_dir / 'aggregates.json'}")


if __name__ == "__main__":
    main()
