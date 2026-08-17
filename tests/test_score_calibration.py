"""Tests for scripts/score_calibration.py.

The value of these is mostly in the arithmetic and the dropping rules. Kappa is checked against a
2x2 table worked out by hand rather than against whatever the code happens to produce, and the
translation between sheet positions and side names is checked by constructing a sheet where half
the pairs are flipped: a rater who always picks the same side must come out as perfect agreement
regardless of where that side was printed.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score_calibration as sc  # noqa: E402

COLUMNS = [*sc.CRITERIA, "overall"]


def make_key(pair_id: str, sheet_a: str, sheet_b: str, judge_winner: str | None,
             per_criterion: dict | None = None) -> dict:
    return {
        "pair_id": pair_id,
        "issue_key": "PIG-600",
        "sub_question": "SQ1",
        "comparison_left": sheet_a,
        "comparison_right": sheet_b,
        "sheet_a": sheet_a,
        "sheet_b": sheet_b,
        "judge_winner": judge_winner,
        "judge_per_criterion": (per_criterion if per_criterion is not None
                                else {c: judge_winner for c in sc.CRITERIA}),
        "judge_positional_inconsistent": judge_winner is None,
    }


def write_case(tmp_path: Path, keys: dict, ratings: dict[str, dict[str, str]]) -> Path:
    """Lay out a calibration directory the way build_calibration_set.py would."""
    cal = tmp_path / "data" / "runs" / "RUN1" / "calibration"
    cal.mkdir(parents=True, exist_ok=True)
    (cal / "key.json").write_text(json.dumps(keys))
    with open(cal / "calibration_ratings.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["pair_id", *COLUMNS])
        for pair_id in sorted(keys):
            row = ratings.get(pair_id, {})
            writer.writerow([pair_id, *[row.get(c, "") for c in COLUMNS]])
    return tmp_path


def score(tmp_path: Path, monkeypatch) -> tuple[int, dict]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["score_calibration.py", "--run-id", "RUN1"])
    code = sc.main()
    result = json.loads(
        (tmp_path / "data" / "runs" / "RUN1" / "calibration" / "result.json").read_text()
    )
    return code, result


def build_2x2(both_a: int, both_b: int, researcher_a_judge_b: int, researcher_b_judge_a: int):
    """A calibration set realising a chosen 2x2 agreement table.

    Every pair puts the same two sides on the sheet in the same orientation, so the researcher's
    letter and the judge's letter are directly the cells of the table being constructed.
    """
    keys: dict[str, dict] = {}
    ratings: dict[str, dict[str, str]] = {}
    cells = ([("A", "A")] * both_a + [("B", "B")] * both_b
             + [("A", "B")] * researcher_a_judge_b + [("B", "A")] * researcher_b_judge_a)
    for i, (rater, judge) in enumerate(cells, start=1):
        pair_id = f"pair_{i:02d}"
        judge_side = "full_rag" if judge == "A" else "vanilla"
        keys[pair_id] = make_key(pair_id, "full_rag", "vanilla", judge_side)
        ratings[pair_id] = {c: rater for c in COLUMNS}
    return keys, ratings


# ---------------------------------------------------------------- kappa arithmetic

def test_kappa_matches_a_hand_computed_table(tmp_path, monkeypatch):
    """Table: 8 both-A, 7 both-B, 3 researcher-A/judge-B, 2 researcher-B/judge-A, n = 20.

    Observed agreement is 15/20 = 0.75. The researcher used A 11 times and B 9; the judge used A 10
    and B 10. Expected agreement is (11*10 + 9*10) / 400 = 0.5. Kappa is (0.75 - 0.5) / 0.5 = 0.5,
    which sits below the 0.6 gate.
    """
    keys, ratings = build_2x2(both_a=8, both_b=7, researcher_a_judge_b=3, researcher_b_judge_a=2)
    write_case(tmp_path, keys, ratings)
    code, result = score(tmp_path, monkeypatch)

    assert result["overall"]["kappa"] == pytest.approx(0.5, abs=1e-4)
    assert result["overall"]["n"] == 20
    assert result["overall"]["raw_agreement"] == pytest.approx(0.75)
    assert result["layer3_validated"] is False
    assert code == 2, "a failed gate exits non-zero"


def test_kappa_above_threshold_passes_the_gate(tmp_path, monkeypatch):
    """9 both-A, 9 both-B, 1 each way: observed 0.9, expected 0.5, kappa 0.8."""
    keys, ratings = build_2x2(both_a=9, both_b=9, researcher_a_judge_b=1, researcher_b_judge_a=1)
    write_case(tmp_path, keys, ratings)
    code, result = score(tmp_path, monkeypatch)

    assert result["overall"]["kappa"] == pytest.approx(0.8, abs=1e-4)
    assert result["layer3_validated"] is True
    assert code == 0


def test_gate_is_read_from_the_calibration_module():
    assert sc.KAPPA_THRESHOLD == 0.6


# ---------------------------------------------------------------- position and side translation

def test_flipped_sheets_do_not_disturb_agreement(tmp_path, monkeypatch):
    """A rater who always prefers the same side agrees perfectly however the sheet was randomised.

    Half the pairs print that side as A and half as B, so a scorer that compared raw letters would
    read this as chance-level disagreement rather than the total agreement it is.
    """
    keys: dict[str, dict] = {}
    ratings: dict[str, dict[str, str]] = {}
    for i in range(1, 21):
        pair_id = f"pair_{i:02d}"
        flipped = i % 2 == 0
        sheet_a, sheet_b = ("vanilla", "full_rag") if flipped else ("full_rag", "vanilla")
        keys[pair_id] = make_key(pair_id, sheet_a, sheet_b, "full_rag")
        # The researcher also picks full_rag every time, which is B on the flipped sheets.
        letter = "B" if flipped else "A"
        ratings[pair_id] = {c: letter for c in COLUMNS}
    write_case(tmp_path, keys, ratings)
    code, result = score(tmp_path, monkeypatch)

    assert result["overall"]["raw_agreement"] == 1.0
    assert all(p["researcher_side"] == "full_rag" for p in result["overall_pairs"])
    assert all(p["judge_side"] == "full_rag" for p in result["overall_pairs"])
    assert all(p["agreed"] for p in result["overall_pairs"])
    assert code == 0


def test_a_judge_side_missing_from_the_sheet_is_fatal(tmp_path, monkeypatch):
    keys = {"pair_01": make_key("pair_01", "full_rag", "vanilla", "reference")}
    write_case(tmp_path, keys, {"pair_01": {c: "A" for c in COLUMNS}})

    with pytest.raises(SystemExit, match="neither side on the sheet"):
        score(tmp_path, monkeypatch)


# ---------------------------------------------------------------- dropping rules

def test_null_judge_criteria_are_dropped_not_imputed(tmp_path, monkeypatch):
    keys, ratings = build_2x2(both_a=9, both_b=9, researcher_a_judge_b=1, researcher_b_judge_a=1)
    # The judge's two presentation orders disagreed on clarity for four pairs, so it holds no
    # reconciled position there and those cells cannot be agreed or disagreed with.
    for pair_id in ("pair_01", "pair_02", "pair_03", "pair_04"):
        keys[pair_id]["judge_per_criterion"]["clarity"] = None
    write_case(tmp_path, keys, ratings)
    _, result = score(tmp_path, monkeypatch)

    assert result["per_criterion"]["clarity"]["n"] == 16
    assert result["per_criterion"]["actionability"]["n"] == 20
    assert result["overall"]["n"] == 20, "a null criterion must not affect the overall column"


def test_blank_ratings_are_dropped(tmp_path, monkeypatch):
    keys, ratings = build_2x2(both_a=9, both_b=9, researcher_a_judge_b=1, researcher_b_judge_a=1)
    for pair_id in ("pair_05", "pair_06"):
        ratings[pair_id]["granularity"] = ""
    ratings["pair_07"]["granularity"] = "n/a"
    write_case(tmp_path, keys, ratings)
    _, result = score(tmp_path, monkeypatch)

    assert result["per_criterion"]["granularity"]["n"] == 17
    assert result["per_criterion"]["clarity"]["n"] == 20


def test_unreadable_ratings_are_refused(tmp_path, monkeypatch):
    keys, ratings = build_2x2(both_a=9, both_b=9, researcher_a_judge_b=1, researcher_b_judge_a=1)
    ratings["pair_03"]["clarity"] = "C"
    ratings["pair_04"]["overall"] = "both"
    write_case(tmp_path, keys, ratings)

    with pytest.raises(SystemExit, match="unreadable ratings"):
        score(tmp_path, monkeypatch)


def test_an_empty_csv_is_refused(tmp_path, monkeypatch):
    keys, _ = build_2x2(both_a=10, both_b=10, researcher_a_judge_b=0, researcher_b_judge_a=0)
    write_case(tmp_path, keys, {})

    with pytest.raises(SystemExit, match="no ratings"):
        score(tmp_path, monkeypatch)


# ---------------------------------------------------------------- degenerate cases

def test_single_label_throughout_reports_undefined_rather_than_nan(tmp_path, monkeypatch):
    """Both raters choosing the same option on all twenty pairs makes chance agreement 1, so kappa
    is undefined. scikit-learn returns nan there, which is not valid JSON and would otherwise fail
    the gate without saying why."""
    keys, ratings = build_2x2(both_a=20, both_b=0, researcher_a_judge_b=0, researcher_b_judge_a=0)
    write_case(tmp_path, keys, ratings)
    code, result = score(tmp_path, monkeypatch)

    block = result["overall"]
    assert block["kappa"] is None
    assert block["usable"] is False
    assert block["raw_agreement"] == 1.0
    assert "undefined" in block["note"]
    assert result["layer3_validated"] is False
    assert code == 2
    # The written file must be readable JSON, which a bare nan would not be.
    raw = (tmp_path / "data" / "runs" / "RUN1" / "calibration" / "result.json").read_text()
    assert "NaN" not in raw
    json.loads(raw)


def test_too_few_usable_pairs_is_reported(tmp_path, monkeypatch):
    keys, ratings = build_2x2(both_a=10, both_b=10, researcher_a_judge_b=0, researcher_b_judge_a=0)
    for pair_id in list(keys)[1:]:
        ratings[pair_id] = {}
    write_case(tmp_path, keys, ratings)
    code, result = score(tmp_path, monkeypatch)

    assert result["overall"]["n"] == 1
    assert result["overall"]["usable"] is False
    assert "fewer than two" in result["overall"]["note"]
    assert code == 2


def test_result_records_how_cells_were_handled(tmp_path, monkeypatch):
    keys, ratings = build_2x2(both_a=9, both_b=9, researcher_a_judge_b=1, researcher_b_judge_a=1)
    write_case(tmp_path, keys, ratings)
    _, result = score(tmp_path, monkeypatch)

    assert result["gate_metric"] == "overall winner"
    assert result["threshold"] == 0.6
    assert result["n_pairs_in_key"] == 20
    assert set(result["per_criterion"]) == set(sc.CRITERIA)
    assert "never imputed" in result["notes"]
